"""Tests for the transcriber module.

All tests mock the OpenAI API — no real API calls are made.
"""

import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import openai

from core.transcriber import (
    transcribe_chunk,
    transcribe_all,
    save_raw_transcript,
    PROMPT_CONTEXT_CHARS,
)


def _make_mock_client(responses, capture_kwargs=None):
    """Create a mock OpenAI client that returns predefined responses.

    Args:
        responses: List of dicts, each with 'text' and 'segments'.
        capture_kwargs: If provided, a list that each call's kwargs are appended to.

    Returns:
        A mock client whose audio.transcriptions.create() returns responses in order.
    """
    client = MagicMock()
    call_count = [0]

    def fake_create(**kwargs):
        if capture_kwargs is not None:
            capture_kwargs.append(kwargs)
        idx = call_count[0]
        call_count[0] += 1
        resp = responses[idx]
        segments = [
            SimpleNamespace(start=s["start"], end=s["end"], text=s["text"])
            for s in resp["segments"]
        ]
        return SimpleNamespace(text=resp["text"], segments=segments)

    client.audio.transcriptions.create = MagicMock(side_effect=fake_create)
    return client


def _create_test_chunks(temp_dir, durations_ms):
    """Create dummy mp3 chunk files. Returns list of chunk paths."""
    chunks = []
    for i, dur_ms in enumerate(durations_ms):
        chunk_path = os.path.join(temp_dir, f"test_chunk_{i+1:03d}.mp3")
        Path(chunk_path).write_bytes(b"\x00" * 100)
        chunks.append(chunk_path)
    return chunks


# ---------------------------------------------------------------------------
# Core functionality tests
# ---------------------------------------------------------------------------

def test_transcribe_chunk_basic():
    """Test that transcribe_chunk returns correct structure from mock API."""
    print("\n=== Testing transcribe_chunk (mock) ===")

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_path = os.path.join(temp_dir, "chunk.mp3")
        Path(chunk_path).write_bytes(b"\x00" * 100)

        mock_client = _make_mock_client([{
            "text": "Hello world, this is a test.",
            "segments": [
                {"start": 0.0, "end": 2.5, "text": " Hello world,"},
                {"start": 2.5, "end": 5.0, "text": " this is a test."},
            ],
        }])

        result = transcribe_chunk(chunk_path, _client_override=mock_client)

        assert result["text"] == "Hello world, this is a test."
        assert len(result["segments"]) == 2
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][1]["end"] == 5.0
        print("✓ transcribe_chunk returns correct structure")
    finally:
        shutil.rmtree(temp_dir)


def test_transcribe_all_concatenation_and_offsets():
    """Test text concatenation and timestamp offsets with 3 chunks.

    Chunk 1 (90s): offset=0    → segments at 0-30, 30-60, 60-90
    Chunk 2 (85s): offset=90   → 0-40→90-130, 40-85→130-175
    Chunk 3 (60s): offset=175  → 0-60→175-235
    """
    print("\n=== Testing transcribe_all (3 chunks, offsets) ===")

    chunk_durations_ms = [90_000, 85_000, 60_000]

    mock_responses = [
        {
            "text": "First chunk transcript.",
            "segments": [
                {"start": 0.0, "end": 30.0, "text": " First part."},
                {"start": 30.0, "end": 60.0, "text": " Second part."},
                {"start": 60.0, "end": 90.0, "text": " Third part."},
            ],
        },
        {
            "text": "Second chunk transcript.",
            "segments": [
                {"start": 0.0, "end": 40.0, "text": " Fourth part."},
                {"start": 40.0, "end": 85.0, "text": " Fifth part."},
            ],
        },
        {
            "text": "Third chunk transcript.",
            "segments": [
                {"start": 0.0, "end": 60.0, "text": " Sixth part."},
            ],
        },
    ]

    mock_client = _make_mock_client(mock_responses)

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_paths = _create_test_chunks(temp_dir, chunk_durations_ms)

        with patch("core.transcriber._get_duration_ms", side_effect=chunk_durations_ms):
            progress_calls = []
            result = transcribe_all(
                chunk_paths,
                progress_callback=lambda c, t: progress_calls.append((c, t)),
                _client_override=mock_client,
            )

        # Text
        expected_text = (
            "First chunk transcript.\n\n"
            "Second chunk transcript.\n\n"
            "Third chunk transcript."
        )
        assert result["full_text"] == expected_text
        print("✓ Text concatenated with double newlines")

        # Timestamp offsets
        segs = result["segments"]
        assert len(segs) == 6
        assert segs[0]["start"] == 0.0 and segs[0]["end"] == 30.0
        assert segs[2]["end"] == 90.0
        assert segs[3]["start"] == 90.0 and segs[3]["end"] == 130.0
        assert segs[4]["start"] == 130.0 and segs[4]["end"] == 175.0
        assert segs[5]["start"] == 175.0 and segs[5]["end"] == 235.0
        print("✓ Timestamp offsets correct")

        # Duration & cost
        assert result["total_duration_seconds"] == 235.0
        expected_cost = round((235.0 / 60) * 0.006, 4)
        assert result["estimated_cost"] == expected_cost
        print(f"✓ Duration={result['total_duration_seconds']}s, cost=${result['estimated_cost']}")

        # Progress & mode
        assert progress_calls == [(1, 3), (2, 3), (3, 3)]
        assert result["mode"] == "sequential"
        print("✓ Progress callback correct, mode=sequential")

    finally:
        shutil.rmtree(temp_dir)


def test_transcribe_all_single_chunk():
    """Edge case: single chunk, no offset needed."""
    print("\n=== Testing transcribe_all (single chunk) ===")

    mock_client = _make_mock_client([{
        "text": "Just one chunk.",
        "segments": [{"start": 0.0, "end": 15.0, "text": " Just one chunk."}],
    }])

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_paths = _create_test_chunks(temp_dir, [15_000])
        with patch("core.transcriber._get_duration_ms", return_value=15_000):
            result = transcribe_all(chunk_paths, _client_override=mock_client)

        assert result["full_text"] == "Just one chunk."
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][0]["end"] == 15.0
        print("✓ Single chunk: no offset, correct output")
    finally:
        shutil.rmtree(temp_dir)


def test_save_raw_transcript():
    """Test saving raw transcript to file."""
    print("\n=== Testing save_raw_transcript ===")

    temp_dir = tempfile.mkdtemp()
    try:
        output_dir = os.path.join(temp_dir, "output")
        text = "This is the full transcript.\n\nWith multiple paragraphs."
        path = save_raw_transcript(text, "interview_2024.mp3", output_dir)

        assert os.path.exists(path)
        assert Path(path).read_text(encoding="utf-8") == text
        assert path.endswith("interview_2024_raw.txt")
        print(f"✓ Saved to {Path(path).name}, content matches")
    finally:
        shutil.rmtree(temp_dir)


# ---------------------------------------------------------------------------
# Retry tests
# ---------------------------------------------------------------------------

def test_retry_logic():
    """Transient errors trigger retries with exponential backoff."""
    print("\n=== Testing retry logic ===")

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_path = os.path.join(temp_dir, "chunk.mp3")
        Path(chunk_path).write_bytes(b"\x00" * 100)

        client = MagicMock()
        call_count = [0]

        def failing_create(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise openai.RateLimitError(
                    message="Rate limit exceeded",
                    response=MagicMock(status_code=429, headers={}),
                    body=None,
                )
            return SimpleNamespace(
                text="Success after retries.",
                segments=[SimpleNamespace(start=0.0, end=5.0, text=" Success.")],
            )

        client.audio.transcriptions.create = MagicMock(side_effect=failing_create)

        with patch("core.transcriber.time.sleep") as mock_sleep:
            result = transcribe_chunk(chunk_path, _client_override=client)

        assert result["text"] == "Success after retries."
        assert call_count[0] == 3
        sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_args == [2, 4]
        print(f"✓ 3 attempts, backoff {sleep_args}")
    finally:
        shutil.rmtree(temp_dir)


def test_retry_exhaustion():
    """3 consecutive failures raise RuntimeError."""
    print("\n=== Testing retry exhaustion ===")

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_path = os.path.join(temp_dir, "chunk.mp3")
        Path(chunk_path).write_bytes(b"\x00" * 100)

        client = MagicMock()
        client.audio.transcriptions.create = MagicMock(
            side_effect=openai.InternalServerError(
                message="Server error",
                response=MagicMock(status_code=500, headers={}),
                body=None,
            )
        )

        with patch("core.transcriber.time.sleep"):
            try:
                transcribe_chunk(chunk_path, _client_override=client)
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "3 attempts" in str(e)
                print(f"✓ RuntimeError: {e}")
    finally:
        shutil.rmtree(temp_dir)


def test_non_retryable_error():
    """Non-retryable errors (AuthenticationError) propagate immediately."""
    print("\n=== Testing non-retryable error ===")

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_path = os.path.join(temp_dir, "chunk.mp3")
        Path(chunk_path).write_bytes(b"\x00" * 100)

        client = MagicMock()
        client.audio.transcriptions.create = MagicMock(
            side_effect=openai.AuthenticationError(
                message="Invalid API key",
                response=MagicMock(status_code=401, headers={}),
                body=None,
            )
        )

        try:
            transcribe_chunk(chunk_path, _client_override=client)
            assert False, "Should have raised AuthenticationError"
        except openai.AuthenticationError:
            print("✓ AuthenticationError raised immediately (no retries)")
    finally:
        shutil.rmtree(temp_dir)


# ---------------------------------------------------------------------------
# Prompt chaining tests
# ---------------------------------------------------------------------------

def test_prompt_chaining_sequential():
    """Verify that sequential mode passes previous chunk's tail as prompt.

    Chunk 1: no prompt (first chunk)
    Chunk 2: prompt = last 200 chars of chunk 1's text
    Chunk 3: prompt = last 200 chars of chunk 2's text
    """
    print("\n=== Testing prompt chaining (sequential) ===")

    chunk_durations_ms = [30_000, 30_000, 30_000]

    text_1 = "A" * 300  # Longer than PROMPT_CONTEXT_CHARS
    text_2 = "B" * 250
    text_3 = "C" * 100

    mock_responses = [
        {"text": text_1, "segments": [{"start": 0.0, "end": 30.0, "text": text_1}]},
        {"text": text_2, "segments": [{"start": 0.0, "end": 30.0, "text": text_2}]},
        {"text": text_3, "segments": [{"start": 0.0, "end": 30.0, "text": text_3}]},
    ]

    captured_kwargs = []
    mock_client = _make_mock_client(mock_responses, capture_kwargs=captured_kwargs)

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_paths = _create_test_chunks(temp_dir, chunk_durations_ms)

        with patch("core.transcriber._get_duration_ms", side_effect=chunk_durations_ms):
            result = transcribe_all(
                chunk_paths,
                parallel=False,  # sequential = prompt chaining
                _client_override=mock_client,
            )

        assert len(captured_kwargs) == 3

        # Chunk 1: no prompt (first chunk has no predecessor)
        assert "prompt" not in captured_kwargs[0] or captured_kwargs[0].get("prompt") is None, \
            f"Chunk 1 should have no prompt, got: {captured_kwargs[0].get('prompt')}"
        print("✓ Chunk 1: no prompt (first chunk)")

        # Chunk 2: prompt = last 200 chars of text_1
        expected_prompt_2 = text_1[-PROMPT_CONTEXT_CHARS:]
        assert captured_kwargs[1]["prompt"] == expected_prompt_2, \
            f"Chunk 2 prompt wrong: {captured_kwargs[1].get('prompt')!r}"
        print(f"✓ Chunk 2: prompt = last {PROMPT_CONTEXT_CHARS} chars of chunk 1")

        # Chunk 3: prompt = last 200 chars of text_2
        expected_prompt_3 = text_2[-PROMPT_CONTEXT_CHARS:]
        assert captured_kwargs[2]["prompt"] == expected_prompt_3
        print(f"✓ Chunk 3: prompt = last {PROMPT_CONTEXT_CHARS} chars of chunk 2")

        assert result["mode"] == "sequential"
        print("✓ Mode reported as 'sequential'")

    finally:
        shutil.rmtree(temp_dir)


def test_prompt_chaining_short_text():
    """When chunk text is shorter than PROMPT_CONTEXT_CHARS, the full text is used."""
    print("\n=== Testing prompt chaining (short text) ===")

    short_text = "Hello."  # Much shorter than 200 chars

    captured_kwargs = []
    mock_client = _make_mock_client(
        [
            {"text": short_text, "segments": [{"start": 0.0, "end": 5.0, "text": short_text}]},
            {"text": "World.", "segments": [{"start": 0.0, "end": 5.0, "text": "World."}]},
        ],
        capture_kwargs=captured_kwargs,
    )

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_paths = _create_test_chunks(temp_dir, [5_000, 5_000])

        with patch("core.transcriber._get_duration_ms", side_effect=[5_000, 5_000]):
            transcribe_all(chunk_paths, parallel=False, _client_override=mock_client)

        # Chunk 2's prompt should be the full short_text (not truncated)
        assert captured_kwargs[1]["prompt"] == short_text
        print(f"✓ Short text '{short_text}' passed as full prompt (no truncation)")
    finally:
        shutil.rmtree(temp_dir)


# ---------------------------------------------------------------------------
# Parallel mode tests
# ---------------------------------------------------------------------------

def test_parallel_mode():
    """Verify parallel mode produces correct results without prompt chaining."""
    print("\n=== Testing parallel mode ===")

    chunk_durations_ms = [60_000, 45_000, 30_000]

    mock_responses = [
        {"text": "Chunk one.", "segments": [{"start": 0.0, "end": 60.0, "text": " Chunk one."}]},
        {"text": "Chunk two.", "segments": [{"start": 0.0, "end": 45.0, "text": " Chunk two."}]},
        {"text": "Chunk three.", "segments": [{"start": 0.0, "end": 30.0, "text": " Chunk three."}]},
    ]

    captured_kwargs = []
    mock_client = _make_mock_client(mock_responses, capture_kwargs=captured_kwargs)

    temp_dir = tempfile.mkdtemp()
    try:
        chunk_paths = _create_test_chunks(temp_dir, chunk_durations_ms)

        with patch("core.transcriber._get_duration_ms", side_effect=chunk_durations_ms):
            progress_calls = []
            result = transcribe_all(
                chunk_paths,
                parallel=True,
                max_workers=2,
                progress_callback=lambda c, t: progress_calls.append((c, t)),
                _client_override=mock_client,
            )

        # Text should be in correct order despite parallel execution
        assert result["full_text"] == "Chunk one.\n\nChunk two.\n\nChunk three."
        print("✓ Text assembled in correct order")

        # Timestamps offset correctly
        segs = result["segments"]
        assert segs[0]["start"] == 0.0 and segs[0]["end"] == 60.0    # chunk 1, offset 0
        assert segs[1]["start"] == 60.0 and segs[1]["end"] == 105.0   # chunk 2, offset 60
        assert segs[2]["start"] == 105.0 and segs[2]["end"] == 135.0  # chunk 3, offset 105
        print("✓ Timestamps offset correctly: 0→60, 60→105, 105→135")

        # No prompt chaining in parallel mode
        for kw in captured_kwargs:
            assert "prompt" not in kw or kw.get("prompt") is None, \
                f"Parallel mode should not use prompt chaining, got: {kw}"
        print("✓ No prompt chaining in parallel mode")

        # Mode
        assert result["mode"] == "parallel"
        print("✓ Mode reported as 'parallel'")

        # Progress called 3 times (order may vary in parallel)
        assert len(progress_calls) == 3
        # All entries should have total=3
        assert all(t == 3 for _, t in progress_calls)
        # Current values should be 1, 2, 3 (in some order)
        assert sorted(c for c, _ in progress_calls) == [1, 2, 3]
        print("✓ Progress callback called 3 times")

        # Duration
        assert result["total_duration_seconds"] == 135.0
        print(f"✓ Duration: {result['total_duration_seconds']}s")

    finally:
        shutil.rmtree(temp_dir)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Core tests
    test_transcribe_chunk_basic()
    test_transcribe_all_concatenation_and_offsets()
    test_transcribe_all_single_chunk()
    test_save_raw_transcript()

    # Retry tests
    test_retry_logic()
    test_retry_exhaustion()
    test_non_retryable_error()

    # Prompt chaining tests
    test_prompt_chaining_sequential()
    test_prompt_chaining_short_text()

    # Parallel mode tests
    test_parallel_mode()

    print("\n" + "=" * 50)
    print("ALL TRANSCRIBER TESTS PASSED!")
    print("=" * 50)
