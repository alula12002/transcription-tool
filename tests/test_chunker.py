"""Tests for the audio chunker module."""

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from core.chunker import (
    calculate_max_chunk_duration,
    process_zip,
    chunk_audio,
    _parse_bitrate_kbps,
    _get_duration_ms,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_ffmpeg():
    """Check if ffmpeg/ffprobe are available on this system."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _create_wav_bytes(duration_ms=5000, sample_rate=16000, channels=1, sample_width=2):
    """Generate a valid WAV file in memory (no ffmpeg needed).

    Creates a silent WAV with a proper header so pydub/ffmpeg can read it.
    """
    import struct

    num_samples = int(sample_rate * duration_ms / 1000)
    data_size = num_samples * channels * sample_width
    # WAV header (44 bytes)
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,          # file size - 8
        b'WAVE',
        b'fmt ',
        16,                       # fmt chunk size
        1,                        # PCM format
        channels,
        sample_rate,
        sample_rate * channels * sample_width,  # byte rate
        channels * sample_width,  # block align
        sample_width * 8,         # bits per sample
        b'data',
        data_size,
    )
    return header + (b'\x00' * data_size)


def _create_test_zip(audio_duration_ms=5000, include_non_audio=False):
    """Create a test zip containing a WAV file.

    Returns (zip_path, temp_dir) — caller must clean up temp_dir.
    """
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir)

    wav_bytes = _create_wav_bytes(duration_ms=audio_duration_ms)
    wav_file = temp_path / "test_audio.wav"
    wav_file.write_bytes(wav_bytes)

    zip_path = temp_path / "test_audio.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(wav_file, arcname="test_audio.wav")
        if include_non_audio:
            # Add a non-audio file
            txt_file = temp_path / "notes.txt"
            txt_file.write_text("not audio")
            zf.write(txt_file, arcname="notes.txt")

    return str(zip_path), temp_dir


# ---------------------------------------------------------------------------
# Tests: Pure logic (no ffmpeg required)
# ---------------------------------------------------------------------------

def test_parse_bitrate():
    """Test that AUDIO_BITRATE ('128k') is parsed to integer 128."""
    print("\n=== Testing _parse_bitrate_kbps ===")
    kbps = _parse_bitrate_kbps()
    assert kbps == 128, f"Expected 128, got {kbps}"
    print(f"✓ Parsed AUDIO_BITRATE to {kbps} kbps")


def test_calculate_max_chunk_duration():
    """Test the max chunk duration calculation."""
    print("\n=== Testing calculate_max_chunk_duration ===")

    max_duration_ms = calculate_max_chunk_duration(bitrate_kbps=128, max_size_mb=24)
    max_duration_sec = max_duration_ms / 1000

    # With 3% safety margin:
    # 24 MB * 0.97 = 23.28 MB safe size
    # 128 kbps = 16,000 bytes/sec
    # max_duration = (23.28 * 1024 * 1024) / 16000 ≈ 1525.68s ≈ 25.4 min
    safe_size_bytes = (24 * 0.97) * 1024 * 1024
    expected_seconds = safe_size_bytes / ((128 * 1000) / 8)

    assert abs(max_duration_sec - expected_seconds) < 0.1, \
        f"Math doesn't match: {max_duration_sec} vs {expected_seconds}"

    print(f"Max chunk duration: {max_duration_sec:.2f}s ({max_duration_sec/60:.1f} min)")
    print("✓ Calculation correct!")


def test_calculate_max_chunk_duration_defaults():
    """Test that calculate_max_chunk_duration uses settings defaults when called with no args."""
    print("\n=== Testing calculate_max_chunk_duration (defaults) ===")

    default_ms = calculate_max_chunk_duration()
    explicit_ms = calculate_max_chunk_duration(bitrate_kbps=128, max_size_mb=24)
    assert default_ms == explicit_ms, f"Default {default_ms} != explicit {explicit_ms}"
    print("✓ Default args match explicit args from settings")


def test_chunk_size_guarantee():
    """Verify that chunks stay under 24MB even with encoding overhead."""
    print("\n=== Testing chunk size guarantee ===")

    max_duration_ms = calculate_max_chunk_duration(bitrate_kbps=128, max_size_mb=24)
    max_duration_sec = max_duration_ms / 1000

    raw_size_bytes = (max_duration_sec * 128 * 1000) / 8
    raw_size_mb = raw_size_bytes / (1024 * 1024)
    with_overhead_mb = raw_size_mb * 1.01  # 1% frame overhead

    print(f"Max duration: {max_duration_sec:.2f}s ({max_duration_sec/60:.1f} min)")
    print(f"Raw size: {raw_size_mb:.2f} MB, with overhead: {with_overhead_mb:.2f} MB")
    print(f"Safety margin: {24 - with_overhead_mb:.2f} MB")

    assert with_overhead_mb <= 24, f"Would exceed 24MB: {with_overhead_mb:.2f}MB"
    print("✓ All chunks guaranteed under 24MB!")


# ---------------------------------------------------------------------------
# Tests: Zip handling
# ---------------------------------------------------------------------------

def test_process_zip_valid():
    """Test extracting audio from a valid zip."""
    print("\n=== Testing process_zip (valid zip) ===")

    zip_path, temp_dir = _create_test_zip(include_non_audio=True)
    work_dir = os.path.join(temp_dir, "extracted")
    try:
        extracted, skipped = process_zip(zip_path, work_dir)
        assert len(extracted) == 1, f"Expected 1 audio file, got {len(extracted)}"
        assert len(skipped) == 1, f"Expected 1 skipped, got {len(skipped)}"
        assert "notes.txt" in skipped[0], f"Expected notes.txt in skipped: {skipped}"
        print(f"✓ Extracted {len(extracted)} audio, skipped {len(skipped)} non-audio")
    finally:
        shutil.rmtree(temp_dir)


def test_process_zip_missing_file():
    """Test that a clear error is raised for a missing zip file."""
    print("\n=== Testing process_zip (missing file) ===")

    try:
        process_zip("/nonexistent/path/fake.zip")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError as e:
        print(f"✓ Got FileNotFoundError: {e}")


def test_process_zip_invalid_zip():
    """Test that a clear error is raised for an invalid zip file."""
    print("\n=== Testing process_zip (invalid zip) ===")

    temp_dir = tempfile.mkdtemp()
    try:
        # Create a file that isn't a zip
        fake_zip = os.path.join(temp_dir, "not_a_zip.zip")
        with open(fake_zip, 'w') as f:
            f.write("this is not a zip file")

        try:
            process_zip(fake_zip)
            assert False, "Should have raised BadZipFile"
        except zipfile.BadZipFile as e:
            print(f"✓ Got BadZipFile: {e}")
    finally:
        shutil.rmtree(temp_dir)


# ---------------------------------------------------------------------------
# Tests: ffmpeg-dependent (skipped if ffmpeg not available)
# ---------------------------------------------------------------------------

def test_get_duration():
    """Test ffprobe-based duration measurement."""
    if not _has_ffmpeg():
        print("\n=== SKIPPED: test_get_duration (ffmpeg not installed) ===")
        return

    print("\n=== Testing _get_duration_ms ===")

    temp_dir = tempfile.mkdtemp()
    try:
        wav_bytes = _create_wav_bytes(duration_ms=3000)
        wav_path = os.path.join(temp_dir, "test.wav")
        with open(wav_path, 'wb') as f:
            f.write(wav_bytes)

        duration = _get_duration_ms(wav_path)
        assert abs(duration - 3000) < 100, f"Expected ~3000ms, got {duration}ms"
        print(f"✓ Duration: {duration}ms (expected ~3000ms)")
    finally:
        shutil.rmtree(temp_dir)


def test_chunk_audio_small_file_no_reencode():
    """Verify that a small file is copied, not re-encoded."""
    if not _has_ffmpeg():
        print("\n=== SKIPPED: test_chunk_audio_small_file_no_reencode (ffmpeg not installed) ===")
        return

    print("\n=== Testing chunk_audio (small file, no re-encode) ===")

    temp_dir = tempfile.mkdtemp()
    try:
        # Create a short WAV, convert to mp3 via ffmpeg
        wav_bytes = _create_wav_bytes(duration_ms=5000)
        wav_path = os.path.join(temp_dir, "short.wav")
        with open(wav_path, 'wb') as f:
            f.write(wav_bytes)

        mp3_path = os.path.join(temp_dir, "short.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-b:a", "128k", "-ac", "1", mp3_path],
            capture_output=True, check=True,
        )
        original_size = os.path.getsize(mp3_path)
        original_bytes = Path(mp3_path).read_bytes()

        # Chunk it — should be a single chunk, copied not re-encoded
        output_dir = os.path.join(temp_dir, "chunks")
        max_dur_ms = calculate_max_chunk_duration()
        chunks, duration_ms = chunk_audio(mp3_path, max_dur_ms, output_dir)

        assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
        chunk_bytes = Path(chunks[0]).read_bytes()
        assert chunk_bytes == original_bytes, "Chunk was re-encoded instead of copied!"
        print(f"✓ Small file copied as-is (not re-encoded), {original_size} bytes")
        print(f"✓ Duration reported: {duration_ms}ms")
    finally:
        shutil.rmtree(temp_dir)


def test_chunk_audio_long_file():
    """Test chunking a longer audio file uses memory-efficient path.

    Creates a ~5-minute silent WAV, converts to mp3, then chunks with a
    small max_duration to force multiple splits. Verifies all chunks exist
    and the memory-efficient ffmpeg path is used (chunk_audio returns duration
    from ffprobe, not from loading the whole file).
    """
    if not _has_ffmpeg():
        print("\n=== SKIPPED: test_chunk_audio_long_file (ffmpeg not installed) ===")
        return

    print("\n=== Testing chunk_audio (long file, forced chunking) ===")
    import subprocess

    temp_dir = tempfile.mkdtemp()
    try:
        # Create 5-minute silent WAV
        wav_bytes = _create_wav_bytes(duration_ms=300_000)  # 5 minutes
        wav_path = os.path.join(temp_dir, "long.wav")
        with open(wav_path, 'wb') as f:
            f.write(wav_bytes)

        # Convert to mp3
        mp3_path = os.path.join(temp_dir, "long.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-b:a", "128k", "-ac", "1", mp3_path],
            capture_output=True, check=True,
        )

        # Chunk with a small limit (60 seconds) to force multiple chunks
        output_dir = os.path.join(temp_dir, "chunks")
        small_max_ms = 60_000  # 60 seconds per chunk

        chunks, total_duration_ms = chunk_audio(mp3_path, small_max_ms, output_dir)

        print(f"  Total duration: {total_duration_ms}ms")
        print(f"  Chunks created: {len(chunks)}")

        # Should produce ~5 chunks (300s / 60s)
        assert len(chunks) >= 4, f"Expected >= 4 chunks, got {len(chunks)}"
        assert len(chunks) <= 7, f"Expected <= 7 chunks, got {len(chunks)}"
        assert abs(total_duration_ms - 300_000) < 1000, \
            f"Duration off: {total_duration_ms}ms vs expected ~300000ms"

        # Verify all chunk files exist and are non-empty
        for i, chunk_path in enumerate(chunks):
            size = os.path.getsize(chunk_path)
            assert size > 0, f"Chunk {i+1} is empty: {chunk_path}"
            print(f"  ✓ Chunk {i+1}: {Path(chunk_path).name} ({size} bytes)")

        print(f"✓ Long file chunked into {len(chunks)} pieces via ffmpeg (memory-efficient)")
    finally:
        shutil.rmtree(temp_dir)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

import subprocess

if __name__ == "__main__":
    has_ff = _has_ffmpeg()
    print(f"ffmpeg available: {has_ff}")

    # Pure logic tests (always run)
    test_parse_bitrate()
    test_calculate_max_chunk_duration()
    test_calculate_max_chunk_duration_defaults()
    test_chunk_size_guarantee()

    # Zip handling tests (no ffmpeg needed)
    test_process_zip_valid()
    test_process_zip_missing_file()
    test_process_zip_invalid_zip()

    # ffmpeg-dependent tests
    test_get_duration()
    test_chunk_audio_small_file_no_reencode()
    test_chunk_audio_long_file()

    print("\n" + "=" * 50)
    if has_ff:
        print("ALL TESTS PASSED!")
    else:
        print("ALL AVAILABLE TESTS PASSED!")
        print("(Install ffmpeg to run audio processing tests)")
    print("=" * 50)
