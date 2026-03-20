"""Send audio chunks to the OpenAI Whisper API and collect transcripts.

Manages per-chunk API calls, retry logic, cost estimation, and
ordered transcript assembly with correct timestamp offsets.

Two transcription modes:
- Sequential (default): Processes chunks in order with prompt chaining —
  the last ~200 characters of each chunk's transcript are passed as context
  to the next chunk, improving accuracy across split boundaries.
- Parallel: Processes chunks concurrently with ThreadPoolExecutor for speed.
  No prompt chaining (since chunks run simultaneously), but results are
  reassembled in the correct order.

Client strategy: A single OpenAI client is created once and reused for all
calls. This avoids re-reading .env and re-initializing HTTP connections on
every chunk, while letting the client's built-in connection pooling work
efficiently.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

import openai
from dotenv import load_dotenv

from config.settings import WHISPER_MODEL, WHISPER_COST_PER_MINUTE
from core.chunker import _get_duration_ms

logger = logging.getLogger(__name__)

# Load .env once at import time
load_dotenv()

# Create a single reusable client
_client = None

# Number of characters from previous chunk to use as prompt context
PROMPT_CONTEXT_CHARS = 200


def _get_client():
    """Return the shared OpenAI client, creating it on first use.

    Lazy initialization so import doesn't fail if the key isn't set yet
    (e.g. during testing with mocks).
    """
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key == "your_key_here":
            raise ValueError(
                "OPENAI_API_KEY not set. Add your key to .env"
            )
        _client = openai.OpenAI(api_key=api_key)
    return _client


# Exceptions that are safe to retry (transient errors)
_RETRYABLE_EXCEPTIONS = (
    openai.APIConnectionError,  # Network issues
    openai.APITimeoutError,     # Request timeout
    openai.RateLimitError,      # 429 rate limit
    openai.InternalServerError, # 500/502/503
)


def transcribe_chunk(chunk_path: str, language: str = "en", prompt: Optional[str] = None,
                     _client_override=None) -> dict:
    """Transcribe a single audio chunk via Whisper API.

    Args:
        chunk_path: Path to the audio file (mp3).
        language: Language code for transcription.
        prompt: Optional text context to improve transcription accuracy.
            Typically the tail end of the previous chunk's transcript.
        _client_override: Optional OpenAI client for testing.

    Returns:
        Dict with 'text' and 'segments' keys. Each segment has
        'start', 'end', and 'text' fields (times in seconds).

    Raises:
        openai.AuthenticationError: If API key is invalid.
        openai.BadRequestError: If the audio file is invalid.
        RuntimeError: If all retry attempts are exhausted.
    """
    client = _client_override or _get_client()
    max_attempts = 3
    backoff_seconds = [2, 4, 8]

    for attempt in range(max_attempts):
        try:
            with open(chunk_path, "rb") as audio_file:
                kwargs = dict(
                    model=WHISPER_MODEL,
                    file=audio_file,
                    language=language,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
                if prompt:
                    kwargs["prompt"] = prompt

                response = client.audio.transcriptions.create(**kwargs)

            # Parse response — verbose_json returns segments with timestamps
            segments = []
            for seg in (response.segments or []):
                segments.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                })

            return {
                "text": response.text,
                "segments": segments,
            }

        except _RETRYABLE_EXCEPTIONS as e:
            if attempt < max_attempts - 1:
                wait = backoff_seconds[attempt]
                logger.warning(
                    f"Whisper API error (attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {wait}s: {e}"
                )
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"Whisper API failed after {max_attempts} attempts: {e}"
                ) from e


def _assemble_results(results_by_index: dict[int, dict], durations_ms_by_index: dict[int, int]) -> dict:
    """Assemble ordered results into final transcript dict.

    Args:
        results_by_index: Dict mapping chunk index to transcribe_chunk result.
        durations_ms_by_index: Dict mapping chunk index to duration in ms.

    Returns:
        Assembled dict with full_text, segments, durations, cost.
    """
    all_text_parts = []
    all_segments = []
    cumulative_offset_sec = 0.0
    total_duration_sec = 0.0

    for i in sorted(results_by_index.keys()):
        result = results_by_index[i]
        chunk_duration_sec = durations_ms_by_index[i] / 1000

        all_text_parts.append(result["text"])

        for seg in result["segments"]:
            all_segments.append({
                "start": round(seg["start"] + cumulative_offset_sec, 3),
                "end": round(seg["end"] + cumulative_offset_sec, 3),
                "text": seg["text"],
            })

        cumulative_offset_sec += chunk_duration_sec
        total_duration_sec += chunk_duration_sec

    total_duration_minutes = total_duration_sec / 60
    estimated_cost = total_duration_minutes * WHISPER_COST_PER_MINUTE

    return {
        "full_text": "\n\n".join(all_text_parts),
        "segments": all_segments,
        "total_duration_seconds": round(total_duration_sec, 2),
        "estimated_cost": round(estimated_cost, 4),
    }


def transcribe_all(chunk_paths: list[str], language: str = "en",
                   progress_callback: Optional[Callable] = None,
                   parallel: bool = False, max_workers: int = 3,
                   _client_override=None) -> dict:
    """Transcribe all chunks and assemble the full transcript.

    Two modes:
    - Sequential (default): Processes in order with prompt chaining.
      Each chunk receives the last ~200 chars of the previous chunk's
      transcript as context, which helps Whisper maintain consistent
      spelling, names, and style across chunk boundaries.
    - Parallel (parallel=True): Processes chunks concurrently for speed.
      No prompt chaining since chunks run simultaneously, but results
      are reassembled in correct order with proper timestamp offsets.

    Timestamp offset logic: Each chunk's segments are relative to that
    chunk's start (0.0s). We offset by the cumulative audio duration
    of all prior chunks to produce a continuous timeline.

    Args:
        chunk_paths: Ordered list of audio chunk file paths.
        language: Language code for transcription.
        progress_callback: Optional fn(current_index, total_chunks) for UI.
        parallel: If True, transcribe chunks concurrently.
        max_workers: Max concurrent API calls in parallel mode (default 3).
        _client_override: Optional OpenAI client for testing.

    Returns:
        Dict with:
            full_text: Concatenated transcript text.
            segments: All segments with adjusted timestamps.
            total_duration_seconds: Total audio duration.
            processing_time_seconds: Wall-clock time for all API calls.
            estimated_cost: Cost estimate based on audio duration.
            mode: "sequential" or "parallel".
    """
    start_time = time.time()
    total_chunks = len(chunk_paths)

    # Fetch all durations once upfront via ffprobe
    durations_ms = {
        i: _get_duration_ms(path) for i, path in enumerate(chunk_paths)
    }

    if parallel:
        results_by_index = _transcribe_parallel(
            chunk_paths, language, max_workers,
            progress_callback, _client_override,
        )
    else:
        results_by_index = _transcribe_sequential(
            chunk_paths, durations_ms, language,
            progress_callback, _client_override,
        )

    assembled = _assemble_results(results_by_index, durations_ms)
    assembled["processing_time_seconds"] = round(time.time() - start_time, 2)
    assembled["mode"] = "parallel" if parallel else "sequential"

    logger.info(
        f"Transcription complete ({assembled['mode']}): "
        f"{total_chunks} chunks, {assembled['total_duration_seconds']}s, "
        f"${assembled['estimated_cost']}, took {assembled['processing_time_seconds']}s"
    )

    return assembled


def _transcribe_sequential(chunk_paths, durations_ms, language,
                           progress_callback, client_override):
    """Transcribe chunks in order with prompt chaining.

    The last PROMPT_CONTEXT_CHARS characters of each chunk's transcript
    are passed as the `prompt` parameter to the next chunk's API call.
    This helps Whisper:
    - Maintain consistent spelling of names and terms
    - Avoid re-introducing punctuation/formatting inconsistencies
    - Handle mid-sentence splits more gracefully
    """
    results = {}
    previous_text_tail = None
    total_chunks = len(chunk_paths)

    for i, chunk_path in enumerate(chunk_paths):
        chunk_duration_sec = durations_ms[i] / 1000

        result = transcribe_chunk(
            chunk_path,
            language=language,
            prompt=previous_text_tail,
            _client_override=client_override,
        )
        results[i] = result

        # Chain: pass tail of this chunk's text as context for the next
        if result["text"]:
            previous_text_tail = result["text"][-PROMPT_CONTEXT_CHARS:]

        if progress_callback:
            progress_callback(i + 1, total_chunks)

        logger.info(
            f"Chunk {i + 1}/{total_chunks} transcribed (sequential): "
            f"{chunk_duration_sec:.1f}s"
        )

    return results


def _transcribe_parallel(chunk_paths, language, max_workers,
                         progress_callback, client_override):
    """Transcribe chunks concurrently, reassemble in order.

    Uses ThreadPoolExecutor since the work is I/O-bound (API calls).
    Results are indexed by chunk position to guarantee correct ordering.
    """
    results = {}
    total_chunks = len(chunk_paths)
    completed = [0]  # mutable counter for callback

    def _do_chunk(index, path):
        return index, transcribe_chunk(
            path, language=language, _client_override=client_override
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_do_chunk, i, path): i
            for i, path in enumerate(chunk_paths)
        }

        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result
            completed[0] += 1

            if progress_callback:
                progress_callback(completed[0], total_chunks)

            logger.info(
                f"Chunk {idx + 1}/{total_chunks} transcribed (parallel)"
            )

    return results


def save_raw_transcript(text: str, original_filename: str, output_dir: str = "output") -> str:
    """Save the raw transcript text to a file.

    Args:
        text: The transcript text to save.
        original_filename: Base name of the original audio file.
        output_dir: Directory to save into (default: "output").

    Returns:
        Path to the saved file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    base_name = Path(original_filename).stem
    file_path = output_path / f"{base_name}_raw.txt"

    file_path.write_text(text, encoding="utf-8")
    logger.info(f"Saved raw transcript: {file_path}")
    return str(file_path)
