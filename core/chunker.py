"""Split large audio files into smaller chunks for transcription.

Handles silence detection and intelligent splitting to stay within
the Whisper API file size limits.

Memory strategy: Instead of loading entire audio files into pydub (which
decompresses to raw PCM in memory), we use ffprobe for metadata and ffmpeg
subprocess calls for chunk extraction via stream copy. Pydub is only used
for silence detection on small 30-second windows near candidate split points.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from config.settings import (
    SUPPORTED_AUDIO_EXTENSIONS,
    MAX_CHUNK_SIZE_MB,
    AUDIO_BITRATE,
    SILENCE_THRESH_DB,
    MIN_SILENCE_LEN_MS,
    SPLIT_SEARCH_WINDOW_MS,
    WHISPER_COST_PER_MINUTE,
)

logger = logging.getLogger(__name__)


def _parse_bitrate_kbps() -> int:
    """Parse AUDIO_BITRATE setting (e.g. '128k') into integer kbps."""
    raw = AUDIO_BITRATE.lower().replace("k", "").strip()
    return int(raw)


def _get_ffmpeg_path() -> str:
    """Return the ffmpeg binary name, or raise if not found."""
    if shutil.which("ffmpeg") is None:
        raise FileNotFoundError(
            "ffmpeg is not installed or not on PATH. "
            "Install it: brew install ffmpeg (macOS), "
            "sudo apt install ffmpeg (Ubuntu), "
            "choco install ffmpeg (Windows)"
        )
    return "ffmpeg"


def _get_ffprobe_path() -> str:
    """Return the ffprobe binary name, or raise if not found."""
    if shutil.which("ffprobe") is None:
        raise FileNotFoundError(
            "ffprobe is not installed or not on PATH. "
            "It is bundled with ffmpeg."
        )
    return "ffprobe"


def _get_duration_ms(file_path: str) -> int:
    """Get audio duration in milliseconds using ffprobe (no audio data loaded).

    This avoids loading the entire file into memory just to check its length.
    """
    ffprobe = _get_ffprobe_path()
    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(file_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    duration_sec = float(info["format"]["duration"])
    return int(duration_sec * 1000)


def _ffmpeg_extract(input_path: str, output_path: str, start_sec: float, duration_sec: float) -> str:
    """Extract a chunk from an mp3 using ffmpeg stream copy (no re-encoding).

    Uses -ss and -t flags to seek and extract. The -c copy flag means the
    audio data is copied byte-for-byte with no transcoding, so this is both
    fast and lossless.
    """
    ffmpeg = _get_ffmpeg_path()
    cmd = [
        ffmpeg, "-y",
        "-ss", f"{start_sec:.3f}",
        "-i", str(input_path),
        "-t", f"{duration_sec:.3f}",
        "-c", "copy",
        "-map", "a:0",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg extraction failed: {result.stderr}")
    return str(output_path)


def _find_silence_split_point(mp3_path: str, candidate_split_ms: int, search_window_ms: int) -> int:
    """Load only a small window near the candidate split point for silence detection.

    Instead of loading the entire file into pydub, we use ffmpeg to extract
    just the search window, then run pydub silence detection on that small buffer.

    Returns the adjusted split point in milliseconds (absolute position in the
    original file), or the original candidate if no silence is found.
    """
    from pydub import AudioSegment
    from pydub.silence import detect_silence

    # Window: from (candidate - search_window) to candidate
    window_start_ms = max(0, candidate_split_ms - search_window_ms)
    window_duration_ms = candidate_split_ms - window_start_ms

    if window_duration_ms <= 0:
        return candidate_split_ms

    # Extract just the window using ffmpeg into a temporary file
    window_path = Path(mp3_path).parent / "_silence_window.mp3"
    try:
        _ffmpeg_extract(
            mp3_path, window_path,
            start_sec=window_start_ms / 1000,
            duration_sec=window_duration_ms / 1000,
        )

        # Load only the small window into pydub for silence detection
        window_audio = AudioSegment.from_file(str(window_path), format="mp3")
        silences = detect_silence(
            window_audio,
            min_silence_len=MIN_SILENCE_LEN_MS,
            silence_thresh=SILENCE_THRESH_DB,
        )

        if silences:
            # Use the last silence gap found in the window (closest to boundary)
            last_silence_start, last_silence_end = silences[-1]
            split_in_window = (last_silence_start + last_silence_end) // 2
            return window_start_ms + split_in_window

        return candidate_split_ms

    except Exception as e:
        logger.warning(f"Silence detection failed, using hard split: {e}")
        return candidate_split_ms
    finally:
        if window_path.exists():
            window_path.unlink()


def process_zip(zip_path: str, work_dir: str = "temp_audio") -> tuple[list[str], list[str]]:
    """Extract audio files from a zip and filter by supported extensions.

    Args:
        zip_path: Path to the zip file.
        work_dir: Directory to extract files into.

    Returns:
        Tuple of (extracted_audio_paths, skipped_filenames).

    Raises:
        FileNotFoundError: If zip_path does not exist.
        zipfile.BadZipFile: If zip_path is not a valid zip file.
    """
    # Validate zip file exists
    zip_file = Path(zip_path)
    if not zip_file.exists():
        raise FileNotFoundError(f"Zip file not found: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise zipfile.BadZipFile(f"Not a valid zip file: {zip_path}")

    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    extracted_files = []
    skipped_files = []

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            if file_info.filename.endswith('/'):
                continue

            file_ext = Path(file_info.filename).suffix.lower()

            if file_ext in SUPPORTED_AUDIO_EXTENSIONS:
                zip_ref.extract(file_info, work_path)
                extracted_path = work_path / file_info.filename
                extracted_files.append(str(extracted_path))
                logger.info(f"Extracted audio file: {file_info.filename}")
            else:
                skipped_files.append(file_info.filename)
                logger.info(f"Skipped non-audio file: {file_info.filename}")

    if skipped_files:
        logger.warning(f"Skipped {len(skipped_files)} non-audio files: {skipped_files}")

    return extracted_files, skipped_files


def _is_mp3(audio_path: str) -> bool:
    """Check if a file is already an mp3 by extension and ffprobe validation."""
    if Path(audio_path).suffix.lower() != ".mp3":
        return False
    # Quick ffprobe check to confirm it's a valid mp3
    try:
        ffprobe = _get_ffprobe_path()
        cmd = [
            ffprobe, "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(audio_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        fmt = info.get("format", {}).get("format_name", "")
        return "mp3" in fmt
    except Exception:
        return False


def convert_to_mp3(audio_path: str, output_dir: str) -> str:
    """Convert an audio file to mp3 (mono, at configured bitrate).

    Skips conversion entirely if the file is already mp3 — just copies it
    to the output directory. This saves significant time for mp3 uploads.

    Uses ffmpeg subprocess for conversion to avoid loading the entire file
    into memory (pydub decompresses to raw PCM which can use hundreds of MB).

    Args:
        audio_path: Path to the input audio file.
        output_dir: Directory to save the converted mp3.

    Returns:
        Path to the output mp3 file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    input_name = Path(audio_path).stem
    output_file = output_path / f"{input_name}.mp3"

    # Skip re-encoding if already mp3 — just copy
    if _is_mp3(audio_path):
        shutil.copy2(audio_path, output_file)
        logger.info(f"Already mp3, copied without re-encoding: {output_file}")
        return str(output_file)

    ffmpeg = _get_ffmpeg_path()
    cmd = [
        ffmpeg, "-y",
        "-i", str(audio_path),
        "-ac", "1",              # mono
        "-b:a", AUDIO_BITRATE,   # e.g. "128k"
        "-map", "a:0",
        str(output_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")
    logger.info(f"Converted to mp3: {output_file}")
    return str(output_file)


def calculate_max_chunk_duration(bitrate_kbps: int | None = None, max_size_mb: int | None = None) -> int:
    """Calculate max audio duration that stays under size limit.

    Args:
        bitrate_kbps: Audio bitrate in kbps. Defaults to parsed AUDIO_BITRATE.
        max_size_mb: Maximum file size in MB. Defaults to MAX_CHUNK_SIZE_MB.

    Returns:
        Maximum duration in milliseconds.
    """
    if bitrate_kbps is None:
        bitrate_kbps = _parse_bitrate_kbps()
    if max_size_mb is None:
        max_size_mb = MAX_CHUNK_SIZE_MB

    # 3% safety margin for mp3 overhead (ID3 tags, frame headers)
    safe_size_bytes = (max_size_mb * 0.97) * 1024 * 1024
    bytes_per_sec = (bitrate_kbps * 1000) / 8
    max_duration_sec = safe_size_bytes / bytes_per_sec
    return int(max_duration_sec * 1000)


def chunk_audio(mp3_path: str, max_duration_ms: int, output_dir: str) -> tuple[list[str], int]:
    """Split an mp3 into chunks, using silence detection near split points.

    Memory-efficient approach:
    - Uses ffprobe for duration (no audio loaded).
    - Uses ffmpeg stream copy for chunk extraction (no re-encoding, no memory).
    - Only loads a 30-second window into pydub for silence detection at each
      candidate split point.
    - If file is already under the limit, copies it directly (no re-encoding).

    Args:
        mp3_path: Path to the mp3 file.
        max_duration_ms: Maximum duration per chunk in milliseconds.
        output_dir: Directory to save chunk files.

    Returns:
        Tuple of (chunk_paths, duration_ms) where chunk_paths is an ordered
        list and duration_ms is the total duration.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    original_name = Path(mp3_path).stem

    # Get duration without loading audio data
    duration_ms = _get_duration_ms(mp3_path)

    # If already under limit, just copy the file — no re-encoding needed
    if duration_ms <= max_duration_ms:
        chunk_file = output_path / f"{original_name}_chunk_001.mp3"
        shutil.copy2(mp3_path, chunk_file)
        logger.info(f"Audio under size limit, copied as single chunk: {chunk_file}")
        return [str(chunk_file)], duration_ms

    # Split into chunks using ffmpeg + windowed silence detection
    chunks = []
    current_pos_ms = 0
    chunk_num = 1

    while current_pos_ms < duration_ms:
        candidate_end_ms = min(current_pos_ms + max_duration_ms, duration_ms)

        # For the last chunk, or if we're at the boundary, just take it
        if candidate_end_ms >= duration_ms:
            split_point_ms = duration_ms
        else:
            # Find a silence gap in the 30s window before the candidate boundary
            split_point_ms = _find_silence_split_point(
                mp3_path, candidate_end_ms, SPLIT_SEARCH_WINDOW_MS
            )

        # Extract chunk via ffmpeg stream copy
        chunk_file = output_path / f"{original_name}_chunk_{chunk_num:03d}.mp3"
        chunk_duration_sec = (split_point_ms - current_pos_ms) / 1000
        _ffmpeg_extract(
            mp3_path, chunk_file,
            start_sec=current_pos_ms / 1000,
            duration_sec=chunk_duration_sec,
        )
        chunks.append(str(chunk_file))
        logger.info(
            f"Exported chunk {chunk_num}: {chunk_file} "
            f"({chunk_duration_sec:.1f}s, {current_pos_ms/1000:.1f}s-{split_point_ms/1000:.1f}s)"
        )

        current_pos_ms = split_point_ms
        chunk_num += 1

    return chunks, duration_ms


def process_audio_files(audio_paths: list[str], cleanup: bool = False) -> dict:
    """Process individual audio files: convert to mp3 and chunk.

    Same as process_upload but skips the zip extraction step. Used when
    users upload individual audio files instead of a zip archive.

    Args:
        audio_paths: List of paths to audio files on disk.
        cleanup: If True, remove temp files after processing.

    Returns:
        Same dict format as process_upload.
    """
    temp_dir = "temp_audio"
    convert_dir = os.path.join(temp_dir, "converted")
    chunks_dir = os.path.join(temp_dir, "chunks")

    try:
        if not audio_paths:
            return {
                "chunk_paths": [],
                "total_duration_seconds": 0,
                "num_chunks": 0,
                "num_files_found": 0,
                "skipped_files": [],
                "estimated_cost": 0,
            }

        # Validate extensions
        valid_files = []
        skipped_files = []
        for path in audio_paths:
            ext = Path(path).suffix.lower()
            if ext in SUPPORTED_AUDIO_EXTENSIONS:
                valid_files.append(path)
            else:
                skipped_files.append(Path(path).name)
                logger.info(f"Skipped unsupported file: {path}")

        if not valid_files:
            logger.warning("No supported audio files provided")
            return {
                "chunk_paths": [],
                "total_duration_seconds": 0,
                "num_chunks": 0,
                "num_files_found": 0,
                "skipped_files": skipped_files,
                "estimated_cost": 0,
            }

        # Convert and chunk each file one at a time, cleaning up as we go
        # to minimize disk usage for large uploads (1GB+ zips)
        bitrate_kbps = _parse_bitrate_kbps()
        max_duration_ms = calculate_max_chunk_duration(bitrate_kbps)

        all_chunks = []
        total_duration_ms = 0

        for audio_file in valid_files:
            # Convert to mp3
            mp3_path = convert_to_mp3(audio_file, convert_dir)

            # Delete source file after conversion to save disk space
            try:
                Path(audio_file).unlink()
                logger.info(f"Cleaned up source file: {audio_file}")
            except OSError:
                pass

            # Chunk the mp3
            chunks, file_duration_ms = chunk_audio(mp3_path, max_duration_ms, chunks_dir)
            all_chunks.extend(chunks)
            total_duration_ms += file_duration_ms

            # Delete converted mp3 after chunking to save disk space
            try:
                Path(mp3_path).unlink()
                logger.info(f"Cleaned up converted file: {mp3_path}")
            except OSError:
                pass

        total_duration_seconds = total_duration_ms / 1000
        total_duration_minutes = total_duration_seconds / 60
        estimated_cost = total_duration_minutes * WHISPER_COST_PER_MINUTE

        result = {
            "chunk_paths": all_chunks,
            "total_duration_seconds": round(total_duration_seconds, 2),
            "num_chunks": len(all_chunks),
            "num_files_found": len(valid_files),
            "skipped_files": skipped_files,
            "estimated_cost": round(estimated_cost, 4),
        }

        logger.info(
            f"Processing complete: {len(all_chunks)} chunks, "
            f"{total_duration_seconds:.2f}s total, ${estimated_cost:.4f} estimated"
        )

        return result

    except Exception as e:
        logger.error(f"Error processing audio files: {e}")
        cleanup_temp_dir(temp_dir)
        raise
    finally:
        if cleanup:
            cleanup_temp_dir(temp_dir)


def cleanup_temp_dir(temp_dir: str = "temp_audio") -> None:
    """Remove the temporary audio processing directory.

    Safe to call even if the directory doesn't exist.
    """
    try:
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temp directory: {temp_dir}")
    except OSError as cleanup_err:
        logger.warning(f"Failed to clean up temp directory {temp_dir}: {cleanup_err}")


def process_upload(zip_path: str, cleanup: bool = False) -> dict:
    """Main orchestrator: unzip, convert to mp3, and chunk audio.

    Args:
        zip_path: Path to the uploaded zip file.
        cleanup: If True, remove temp files after processing. Set to False
            (default) when chunk files need to survive for a later
            transcription step. Call cleanup_temp_dir() manually when done.

    Returns:
        Dict with:
            chunk_paths: Ordered list of chunk file paths.
            total_duration_seconds: Total duration of all audio.
            num_chunks: Total number of chunks created.
            num_files_found: Number of audio files extracted.
            skipped_files: List of non-audio file names.
            estimated_cost: Estimated Whisper API cost.
    """
    temp_dir = "temp_audio"
    convert_dir = os.path.join(temp_dir, "converted")
    chunks_dir = os.path.join(temp_dir, "chunks")

    try:
        # Step 1: Extract from zip
        extracted_files, skipped_files = process_zip(zip_path, temp_dir)
        if not extracted_files:
            logger.warning("No audio files found in zip")
            return {
                "chunk_paths": [],
                "total_duration_seconds": 0,
                "num_chunks": 0,
                "num_files_found": 0,
                "skipped_files": skipped_files,
                "estimated_cost": 0,
            }

        # Step 2 & 3: Convert and chunk each file one at a time,
        # cleaning up as we go to minimize disk usage for large zips (1GB+)
        bitrate_kbps = _parse_bitrate_kbps()
        max_duration_ms = calculate_max_chunk_duration(bitrate_kbps)

        all_chunks = []
        total_duration_ms = 0

        for audio_file in extracted_files:
            # Convert to mp3
            mp3_path = convert_to_mp3(audio_file, convert_dir)

            # Delete extracted source file after conversion
            try:
                Path(audio_file).unlink()
                logger.info(f"Cleaned up extracted file: {audio_file}")
            except OSError:
                pass

            # Chunk the mp3
            chunks, file_duration_ms = chunk_audio(mp3_path, max_duration_ms, chunks_dir)
            all_chunks.extend(chunks)
            total_duration_ms += file_duration_ms

            # Delete converted mp3 after chunking
            try:
                Path(mp3_path).unlink()
                logger.info(f"Cleaned up converted file: {mp3_path}")
            except OSError:
                pass

        total_duration_seconds = total_duration_ms / 1000
        total_duration_minutes = total_duration_seconds / 60
        estimated_cost = total_duration_minutes * WHISPER_COST_PER_MINUTE

        result = {
            "chunk_paths": all_chunks,
            "total_duration_seconds": round(total_duration_seconds, 2),
            "num_chunks": len(all_chunks),
            "num_files_found": len(extracted_files),
            "skipped_files": skipped_files,
            "estimated_cost": round(estimated_cost, 4),
        }

        logger.info(
            f"Processing complete: {len(all_chunks)} chunks, "
            f"{total_duration_seconds:.2f}s total, ${estimated_cost:.4f} estimated"
        )

        return result

    except Exception as e:
        logger.error(f"Error processing upload: {e}")
        # Always cleanup on error so we don't leave partial state
        cleanup_temp_dir(temp_dir)
        raise
    finally:
        if cleanup:
            cleanup_temp_dir(temp_dir)
