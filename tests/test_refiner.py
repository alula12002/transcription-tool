"""Tests for the refiner module.

All tests mock the Anthropic API — no real API calls are made.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from core.refiner import (
    load_prompt,
    split_transcript_for_context,
    refine_transcript,
    estimate_refinement_cost,
    _deduplicate_overlap,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(responses, capture_calls=None, tokens_per_call=500):
    """Create a mock Anthropic client that returns predefined responses.

    Args:
        responses: List of response text strings, one per API call.
        capture_calls: If provided, a list that each call's kwargs are appended to.
        tokens_per_call: Simulated token count per call for usage tracking.

    Returns:
        A mock client whose messages.create() returns responses in order.
    """
    client = MagicMock()
    call_count = [0]

    def fake_create(**kwargs):
        if capture_calls is not None:
            capture_calls.append(kwargs)
        idx = call_count[0]
        call_count[0] += 1
        return SimpleNamespace(
            content=[SimpleNamespace(text=responses[idx])],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=tokens_per_call,
                output_tokens=tokens_per_call // 2,
            ),
        )

    client.messages.create = MagicMock(side_effect=fake_create)
    return client


# ---------------------------------------------------------------------------
# Tests: Prompt loading
# ---------------------------------------------------------------------------

def test_load_prompt_raw_cleanup():
    """Test loading the raw_cleanup prompt template."""
    print("\n=== Testing load_prompt('raw_cleanup') ===")
    prompt = load_prompt("raw_cleanup")
    assert "transcription editor" in prompt.lower()
    assert "punctuation" in prompt.lower()
    assert len(prompt) > 100
    print(f"✓ Loaded raw_cleanup prompt ({len(prompt)} chars)")


def test_load_prompt_structured_prose():
    """Test loading the structured_prose prompt template."""
    print("\n=== Testing load_prompt('structured_prose') ===")
    prompt = load_prompt("structured_prose")
    assert "oral history editor" in prompt.lower()
    assert "voice" in prompt.lower()
    assert len(prompt) > 100
    print(f"✓ Loaded structured_prose prompt ({len(prompt)} chars)")


def test_load_prompt_summary():
    """Test loading the summary prompt template."""
    print("\n=== Testing load_prompt('summary') ===")
    prompt = load_prompt("summary")
    assert "summary" in prompt.lower()
    assert "third person" in prompt.lower()
    assert len(prompt) > 100
    print(f"✓ Loaded summary prompt ({len(prompt)} chars)")


def test_load_prompt_invalid_mode():
    """Test that an invalid mode raises ValueError."""
    print("\n=== Testing load_prompt('nonexistent') ===")
    try:
        load_prompt("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "nonexistent" in str(e)
        print(f"✓ Got ValueError: {e}")


# ---------------------------------------------------------------------------
# Tests: Transcript splitting
# ---------------------------------------------------------------------------

def test_split_short_text():
    """Short text should return a single-item list."""
    print("\n=== Testing split_transcript_for_context (short text) ===")
    text = "This is a short transcript."
    sections = split_transcript_for_context(text, max_chars=1000, overlap_chars=50)
    assert len(sections) == 1
    assert sections[0] == text
    print("✓ Short text returned as single section")


def test_split_long_text_at_paragraphs():
    """Long text should split at paragraph boundaries with overlap."""
    print("\n=== Testing split_transcript_for_context (long text) ===")

    # Create text with clear paragraph breaks
    paragraphs = []
    for i in range(20):
        paragraphs.append(f"Paragraph {i}: " + "word " * 50)
    text = "\n\n".join(paragraphs)

    # Split with a small max to force multiple sections
    sections = split_transcript_for_context(text, max_chars=500, overlap_chars=100)

    print(f"  Total text length: {len(text)} chars")
    print(f"  Sections created: {len(sections)}")

    assert len(sections) > 1, "Should have split into multiple sections"

    # Each section should be under max_chars (or close)
    for i, section in enumerate(sections):
        print(f"  Section {i+1}: {len(section)} chars")
        assert len(section) <= 600, f"Section {i+1} too long: {len(section)}"

    # All original content should be covered
    assert "Paragraph 0:" in sections[0]
    assert "Paragraph 19:" in sections[-1]

    print("✓ Long text split correctly at paragraph boundaries")


def test_split_overlap_continuity():
    """Verify overlap content appears in consecutive sections."""
    print("\n=== Testing split overlap continuity ===")

    # Build text with unique markers at known positions
    parts = []
    for i in range(10):
        parts.append(f"[MARKER_{i}] " + "x" * 200)
    text = "\n\n".join(parts)

    sections = split_transcript_for_context(text, max_chars=800, overlap_chars=200)

    assert len(sections) >= 2, "Need at least 2 sections for overlap test"

    # Check that the tail of section N overlaps into section N+1
    for i in range(len(sections) - 1):
        tail = sections[i][-200:]
        overlap_found = any(
            word in sections[i + 1][:400]
            for word in tail.split()
            if len(word) > 3
        )
        assert overlap_found, f"No overlap found between sections {i} and {i+1}"

    print(f"✓ Overlap verified across {len(sections)} sections")


# ---------------------------------------------------------------------------
# Tests: Overlap deduplication
# ---------------------------------------------------------------------------

def test_deduplicate_overlap_removes_duplicate():
    """Test that overlapping content is trimmed from the second section."""
    print("\n=== Testing _deduplicate_overlap (with overlap) ===")

    previous = (
        "The narrator described growing up in a small town. "
        "He talked about the old mill by the river where his father worked. "
        "Every morning they would walk together down the dusty road."
    )
    # current starts with a repeated chunk from previous's tail
    overlap = "his father worked. Every morning they would walk together down the dusty road."
    current = (
        f"{overlap} "
        "The summers were long and hot. They would swim in the creek after school. "
        "His mother always had lemonade waiting on the porch."
    )

    result = _deduplicate_overlap(previous, current)

    # The repeated part should be trimmed
    assert "His mother always had lemonade" in result
    # The result should be shorter than the original
    assert len(result) < len(current)
    print(f"✓ Trimmed overlap: {len(current)} -> {len(result)} chars")


def test_deduplicate_overlap_no_overlap():
    """Test that non-overlapping content is left untouched."""
    print("\n=== Testing _deduplicate_overlap (no overlap) ===")

    previous = "This is the first section about childhood memories."
    current = "Now we move on to the war years and military service."

    result = _deduplicate_overlap(previous, current)
    assert result == current
    print("✓ Non-overlapping text left untouched")


def test_deduplicate_overlap_empty_inputs():
    """Test graceful handling of empty strings."""
    print("\n=== Testing _deduplicate_overlap (empty inputs) ===")

    assert _deduplicate_overlap("", "some text") == "some text"
    assert _deduplicate_overlap("some text", "") == ""
    assert _deduplicate_overlap("", "") == ""
    print("✓ Empty inputs handled gracefully")


# ---------------------------------------------------------------------------
# Tests: Cost estimation
# ---------------------------------------------------------------------------

def test_estimate_refinement_cost_summary():
    """Test cost estimation for summary mode."""
    print("\n=== Testing estimate_refinement_cost (summary) ===")

    # 40,000 chars ≈ 10,000 tokens input
    raw_text = "word " * 8000  # 40,000 chars
    estimate = estimate_refinement_cost(raw_text, mode="summary")

    assert estimate["estimated_cost"] > 0
    assert estimate["estimated_input_tokens"] > 0
    assert estimate["estimated_output_tokens"] > 0
    # Summary output should be much less than input
    assert estimate["estimated_output_tokens"] < estimate["estimated_input_tokens"]

    print(f"  Input tokens: {estimate['estimated_input_tokens']}")
    print(f"  Output tokens: {estimate['estimated_output_tokens']}")
    print(f"  Estimated cost: ${estimate['estimated_cost']:.4f}")
    print("✓ Summary cost estimate looks reasonable")


def test_estimate_refinement_cost_raw_cleanup():
    """Test cost estimation for raw_cleanup mode (output ≈ input)."""
    print("\n=== Testing estimate_refinement_cost (raw_cleanup) ===")

    raw_text = "word " * 8000
    estimate = estimate_refinement_cost(raw_text, mode="raw_cleanup")

    # Raw cleanup output should be roughly same length as input
    assert estimate["estimated_output_tokens"] >= estimate["estimated_input_tokens"] * 0.8

    print(f"  Input tokens: {estimate['estimated_input_tokens']}")
    print(f"  Output tokens: {estimate['estimated_output_tokens']}")
    print(f"  Estimated cost: ${estimate['estimated_cost']:.4f}")
    print("✓ Raw cleanup cost estimate looks reasonable")


def test_estimate_cost_modes_differ():
    """Summary should be cheaper than raw_cleanup for the same input."""
    print("\n=== Testing cost varies by mode ===")

    raw_text = "word " * 8000
    summary_cost = estimate_refinement_cost(raw_text, mode="summary")["estimated_cost"]
    cleanup_cost = estimate_refinement_cost(raw_text, mode="raw_cleanup")["estimated_cost"]

    assert summary_cost < cleanup_cost, (
        f"Summary (${summary_cost}) should be cheaper than cleanup (${cleanup_cost})"
    )
    print(f"  Summary: ${summary_cost:.4f}, Raw cleanup: ${cleanup_cost:.4f}")
    print("✓ Summary mode is cheaper than raw cleanup")


# ---------------------------------------------------------------------------
# Tests: Refinement with mocked API
# ---------------------------------------------------------------------------

def test_refine_short_transcript():
    """Test refinement of a short transcript (single section, no splitting)."""
    print("\n=== Testing refine_transcript (short text) ===")

    mock_response = "Refined version of the transcript."
    captured = []
    client = _make_mock_client([mock_response], capture_calls=captured)

    result = refine_transcript(
        "This is a short raw transcript.",
        mode="raw_cleanup",
        _client_override=client,
    )

    assert result["refined_text"] == mock_response
    assert result["mode"] == "raw_cleanup"
    assert result["sections_processed"] == 1
    assert result["actual_cost"] >= 0
    assert result["total_input_tokens"] > 0
    assert result["total_output_tokens"] > 0
    assert len(captured) == 1

    # Verify the system prompt was loaded correctly
    system_msg = captured[0]["system"]
    assert "transcription editor" in system_msg.lower()

    print(f"✓ Refined text: '{result['refined_text'][:50]}...'")
    print(f"✓ Cost: ${result['actual_cost']:.4f} "
          f"({result['total_input_tokens']} in, {result['total_output_tokens']} out)")


def test_refine_with_user_instructions():
    """Test that user instructions are appended to the user message."""
    print("\n=== Testing refine_transcript with user_instructions ===")

    captured = []
    client = _make_mock_client(["Refined output."], capture_calls=captured)

    refine_transcript(
        "Raw transcript text here.",
        mode="structured_prose",
        user_instructions="The narrator's name is Frank. He grew up in Detroit.",
        _client_override=client,
    )

    user_msg = captured[0]["messages"][0]["content"]
    assert "Additional context from the user:" in user_msg
    assert "Frank" in user_msg
    assert "Detroit" in user_msg
    print("✓ User instructions appended to API call")


def test_refine_long_transcript_multiple_sections():
    """Test refinement of a long transcript that requires splitting."""
    print("\n=== Testing refine_transcript (multi-section) ===")

    # Build a transcript longer than max_chars
    raw_text = "\n\n".join([f"Story {i}: " + "word " * 2000 for i in range(10)])
    print(f"  Raw text length: {len(raw_text)} chars")

    # One response per section
    sections = split_transcript_for_context(raw_text)
    num_sections = len(sections)
    print(f"  Expected sections: {num_sections}")

    mock_responses = [f"Refined section {i+1}." for i in range(num_sections)]
    progress_calls = []

    def progress_cb(current, total):
        progress_calls.append((current, total))

    client = _make_mock_client(mock_responses)

    result = refine_transcript(
        raw_text,
        mode="summary",
        progress_callback=progress_cb,
        _client_override=client,
    )

    assert result["sections_processed"] == num_sections
    assert result["mode"] == "summary"
    assert result["total_input_chars"] == len(raw_text)
    assert result["actual_cost"] >= 0
    # Token counts should accumulate across sections
    assert result["total_input_tokens"] == 500 * num_sections
    assert result["total_output_tokens"] == 250 * num_sections

    # Verify all sections are in the output
    for i in range(num_sections):
        assert f"Refined section {i+1}." in result["refined_text"]

    # Verify progress callback was called correctly
    assert len(progress_calls) == num_sections
    assert progress_calls[-1] == (num_sections, num_sections)

    print(f"✓ {num_sections} sections processed and concatenated")
    print(f"✓ Cost: ${result['actual_cost']:.4f} "
          f"({result['total_input_tokens']} in, {result['total_output_tokens']} out)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Prompt loading
    test_load_prompt_raw_cleanup()
    test_load_prompt_structured_prose()
    test_load_prompt_summary()
    test_load_prompt_invalid_mode()

    # Transcript splitting
    test_split_short_text()
    test_split_long_text_at_paragraphs()
    test_split_overlap_continuity()

    # Overlap deduplication
    test_deduplicate_overlap_removes_duplicate()
    test_deduplicate_overlap_no_overlap()
    test_deduplicate_overlap_empty_inputs()

    # Cost estimation
    test_estimate_refinement_cost_summary()
    test_estimate_refinement_cost_raw_cleanup()
    test_estimate_cost_modes_differ()

    # Refinement with mock API
    test_refine_short_transcript()
    test_refine_with_user_instructions()
    test_refine_long_transcript_multiple_sections()

    print("\n" + "=" * 50)
    print("ALL REFINER TESTS PASSED!")
    print("=" * 50)
