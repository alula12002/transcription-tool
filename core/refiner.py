"""Refine raw transcripts using Claude with selectable refinement modes.

Supports raw cleanup, structured prose, and summary modes via
corresponding prompt templates.

Client strategy: Same lazy-init pattern as transcriber.py — a single
Anthropic client is created on first use and reused for all calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Optional

import anthropic

from config.settings import (
    CLAUDE_MODEL,
    CLAUDE_COST_PER_INPUT_TOKEN,
    CLAUDE_COST_PER_OUTPUT_TOKEN,
    MAX_TRANSCRIPT_CHARS_PER_CALL,
    OVERLAP_CHARS,
    REFINEMENT_MODES,
)

logger = logging.getLogger(__name__)

# Shared Anthropic client
_client = None

# Directory containing prompt template files
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Cache directory for refined sections (resumability)
_CACHE_DIR = Path(__file__).resolve().parent.parent / "temp_audio" / "refine_cache"


def _section_cache_key(section_text: str, mode: str, user_instructions: Optional[str]) -> str:
    """Generate a unique cache key for a section + mode + instructions combo."""
    content = f"{mode}|{user_instructions or ''}|{section_text}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _get_cached_section(cache_key: str) -> Optional[dict]:
    """Load a cached refined section if it exists."""
    cache_file = _CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            logger.info(f"Cache hit for section {cache_key}")
            return data
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_section_cache(cache_key: str, result: dict) -> None:
    """Save a refined section to cache."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _CACHE_DIR / f"{cache_key}.json"
    try:
        cache_file.write_text(json.dumps(result), encoding="utf-8")
    except OSError as e:
        logger.warning(f"Failed to cache section {cache_key}: {e}")


def _get_client():
    """Return the shared Anthropic client, creating it on first use.

    Lazy initialization so import doesn't fail if the key isn't set yet
    (e.g. during testing with mocks).
    """
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_key_here":
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Add your key to .env"
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def load_prompt(mode: str) -> str:
    """Read a prompt template file for the given refinement mode.

    Args:
        mode: One of the keys in REFINEMENT_MODES (e.g. 'raw_cleanup').

    Returns:
        The prompt text as a string.

    Raises:
        ValueError: If mode is not a recognized refinement mode.
        FileNotFoundError: If the prompt template file is missing.
    """
    if mode not in REFINEMENT_MODES:
        available = ", ".join(REFINEMENT_MODES.keys())
        raise ValueError(
            f"Unknown refinement mode '{mode}'. Available modes: {available}"
        )

    prompt_file = _PROMPTS_DIR / f"{mode}.txt"
    if not prompt_file.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {prompt_file}"
        )

    return prompt_file.read_text(encoding="utf-8").strip()


def split_transcript_for_context(text: str, max_chars: Optional[int] = None, overlap_chars: Optional[int] = None) -> list[str]:
    """Split a long transcript into sections that fit within the context window.

    Splits at paragraph boundaries (\\n\\n) to avoid cutting mid-sentence.
    Each section after the first includes the last overlap_chars of the
    previous section for continuity.

    Args:
        text: The full transcript text.
        max_chars: Maximum characters per section. Defaults to settings.
        overlap_chars: Characters of overlap between sections. Defaults to settings.

    Returns:
        List of text sections. Single-item list if text is short enough.
    """
    if max_chars is None:
        max_chars = MAX_TRANSCRIPT_CHARS_PER_CALL
    if overlap_chars is None:
        overlap_chars = OVERLAP_CHARS

    if len(text) <= max_chars:
        return [text]

    sections = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            sections.append(remaining)
            break

        # Find the last paragraph break within the limit
        chunk = remaining[:max_chars]
        split_pos = chunk.rfind("\n\n")

        if split_pos == -1 or split_pos < max_chars // 2:
            # No good paragraph break — fall back to last space
            split_pos = chunk.rfind(" ")
            if split_pos == -1:
                # No space at all — hard split
                split_pos = max_chars

        sections.append(remaining[:split_pos])

        # Advance past the split, but overlap for continuity
        next_start = max(0, split_pos - overlap_chars)
        remaining = remaining[next_start:]

        # Avoid infinite loop if overlap pushes us back to the same spot
        if len(remaining) >= len(text):
            sections.append(remaining)
            break

    return sections


# Exceptions that are safe to retry (transient errors)
_RETRYABLE_EXCEPTIONS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def _call_claude(system_prompt: str, user_message: str, max_tokens: int = 4096,
                 _client_override=None) -> dict:
    """Make a single Claude API call with retry logic.

    Args:
        system_prompt: The system message (prompt template).
        user_message: The user message (transcript section).
        max_tokens: Maximum tokens in the response.
        _client_override: Optional client for testing.

    Returns:
        Dict with 'text', 'input_tokens', and 'output_tokens'.

    Raises:
        anthropic.AuthenticationError: If API key is invalid.
        anthropic.BadRequestError: If the request is malformed.
        RuntimeError: If all retry attempts are exhausted.
    """
    client = _client_override or _get_client()
    max_attempts = 3
    backoff_seconds = [2, 4, 8]

    for attempt in range(max_attempts):
        try:
            with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                response = stream.get_final_message()

            # Check for truncation
            if response.stop_reason == "max_tokens":
                logger.warning(
                    f"Response truncated at {max_tokens} tokens. "
                    f"Consider increasing max_tokens for long sections."
                )

            # Extract token usage (graceful fallback for mocks)
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

            return {
                "text": response.content[0].text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

        except _RETRYABLE_EXCEPTIONS as e:
            if attempt < max_attempts - 1:
                wait = backoff_seconds[attempt]
                logger.warning(
                    f"Claude API error (attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {wait}s: {e}"
                )
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"Claude API failed after {max_attempts} attempts: {e}"
                ) from e


def _deduplicate_overlap(previous_text: str, current_text: str, min_match_len: int = 40) -> str:
    """Remove overlapping content from the start of current_text.

    When sections are split with overlap, the refined output for section N+1
    may start with content that duplicates the end of section N's output.
    This function finds and trims that overlap.

    Uses SequenceMatcher to find the longest common substring between the
    tail of previous_text and the head of current_text. If a match of at
    least min_match_len chars is found at the start of current_text, it's
    trimmed.

    Args:
        previous_text: The refined output of the previous section.
        current_text: The refined output of the current section.
        min_match_len: Minimum match length to consider as real overlap.

    Returns:
        current_text with leading overlap removed.
    """
    if not previous_text or not current_text:
        return current_text

    # Compare the last ~2000 chars of previous with first ~2000 of current
    tail = previous_text[-2000:]
    head = current_text[:2000]

    matcher = SequenceMatcher(None, tail, head)
    match = matcher.find_longest_match(0, len(tail), 0, len(head))

    # match.b is where the match starts in `head` (current_text[:2000])
    # We only trim if the match is near the start of current_text and long enough
    if match.size >= min_match_len and match.b < 200:
        trim_point = match.b + match.size
        # Advance to the next paragraph or sentence boundary after the match
        next_para = current_text.find("\n\n", trim_point)
        next_sentence = current_text.find(". ", trim_point)

        if next_para != -1 and next_para < trim_point + 200:
            trim_point = next_para + 2  # skip past \n\n
        elif next_sentence != -1 and next_sentence < trim_point + 100:
            trim_point = next_sentence + 2  # skip past ". "

        trimmed = current_text[trim_point:].lstrip()
        if trimmed:
            logger.info(
                f"Deduplicated {trim_point} chars of overlap "
                f"(match: {match.size} chars)"
            )
            return trimmed

    return current_text


def estimate_refinement_cost(raw_text: str, mode: str = "structured_prose") -> dict:
    """Estimate the Claude API cost for refining a transcript.

    Provides a rough estimate based on character count and typical
    token ratios. Actual cost depends on the model's tokenizer.

    Args:
        raw_text: The raw transcript text.
        mode: Refinement mode (affects expected output length).

    Returns:
        Dict with estimated_cost, estimated_input_tokens, estimated_output_tokens.
    """
    # ~4 chars per token for English text
    input_tokens = len(raw_text) // 4
    # Add ~300 tokens for system prompt
    input_tokens += 300

    # Output length depends on mode
    if mode == "summary":
        output_tokens = input_tokens // 8   # ~12.5% of input
    elif mode == "raw_cleanup":
        output_tokens = input_tokens         # roughly same length
    else:
        output_tokens = int(input_tokens * 0.8)  # slightly shorter

    cost = (
        input_tokens * CLAUDE_COST_PER_INPUT_TOKEN
        + output_tokens * CLAUDE_COST_PER_OUTPUT_TOKEN
    )

    return {
        "estimated_cost": round(cost, 4),
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
    }


def _refine_single_section(
    index: int,
    section: str,
    system_prompt: str,
    mode: str,
    user_instructions: Optional[str],
    _client_override=None,
) -> tuple[int, dict, str]:
    """Refine a single section. Used by both sequential and parallel modes.

    Returns:
        Tuple of (index, api_result_dict, cache_key).
    """
    cache_key = _section_cache_key(section, mode, user_instructions)

    # Check cache first (resumability)
    cached = _get_cached_section(cache_key)
    if cached:
        return (index, cached, cache_key)

    # Build user message
    user_message = section
    if user_instructions:
        user_message += f"\n\nAdditional context from the user: {user_instructions}"

    # Scale max_tokens based on section length and mode.
    # Raw cleanup output ≈ same length as input, structured prose ≈ 80%,
    # summary ≈ 12.5%. The ~3 chars/token estimate is conservative.
    estimated_output_tokens = len(section) // 3
    if mode == "summary":
        estimated_output_tokens = estimated_output_tokens // 4
    elif mode == "structured_prose":
        estimated_output_tokens = int(estimated_output_tokens * 0.85)
    # Floor of 4096, cap of 32000 (well within Sonnet's 64K limit)
    max_tokens = max(4096, min(estimated_output_tokens, 32000))

    result = _call_claude(
        system_prompt,
        user_message,
        max_tokens=max_tokens,
        _client_override=_client_override,
    )

    # Cache the result for resumability
    _save_section_cache(cache_key, result)

    return (index, result, cache_key)


def refine_transcript(raw_text: str, mode: str, user_instructions: Optional[str] = None,
                      progress_callback: Optional[Callable] = None,
                      parallel: bool = False, max_workers: int = 4,
                      _client_override=None) -> dict:
    """Refine a raw transcript using Claude with the selected mode.

    Args:
        raw_text: The raw transcript text.
        mode: Refinement mode key (e.g. 'raw_cleanup', 'structured_prose', 'summary').
        user_instructions: Optional additional context from the user
            (e.g. names, places, dates) appended to the transcript.
        progress_callback: Optional fn(current_section, total_sections) for UI.
        parallel: If True, process all sections concurrently (faster but
            section transitions may be less smooth).
        max_workers: Max concurrent API calls when parallel=True.
        _client_override: Optional Anthropic client for testing.

    Returns:
        Dict with:
            refined_text: The refined transcript.
            mode: The refinement mode used.
            sections_processed: Number of sections sent to the API.
            total_input_chars: Total characters of input text.
            total_input_tokens: Actual input tokens used (from API).
            total_output_tokens: Actual output tokens used (from API).
            actual_cost: Cost based on actual token usage from API.
    """
    system_prompt = load_prompt(mode)
    sections = split_transcript_for_context(raw_text)
    total_sections = len(sections)

    logger.info(
        f"Refining transcript: mode={mode}, parallel={parallel}, "
        f"{total_sections} section(s), {len(raw_text)} chars"
    )

    total_input_tokens = 0
    total_output_tokens = 0

    # Collect results indexed by section position
    results_by_index: dict[int, dict] = {}
    completed = 0

    if parallel and total_sections > 1:
        # --- Parallel mode: all sections at once ---
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _refine_single_section,
                    i, section, system_prompt, mode, user_instructions,
                    _client_override,
                ): i
                for i, section in enumerate(sections)
            }

            for future in as_completed(futures):
                idx, result, cache_key = future.result()
                results_by_index[idx] = result
                completed += 1
                total_input_tokens += result["input_tokens"]
                total_output_tokens += result["output_tokens"]
                logger.info(f"Section {idx + 1}/{total_sections} refined (parallel)")

                if progress_callback:
                    progress_callback(completed, total_sections)
    else:
        # --- Sequential mode: one at a time ---
        for i, section in enumerate(sections):
            idx, result, cache_key = _refine_single_section(
                i, section, system_prompt, mode, user_instructions,
                _client_override,
            )
            results_by_index[idx] = result
            completed += 1
            total_input_tokens += result["input_tokens"]
            total_output_tokens += result["output_tokens"]
            logger.info(f"Section {i + 1}/{total_sections} refined")

            if progress_callback:
                progress_callback(completed, total_sections)

    # Reassemble in order and deduplicate overlaps
    refined_parts = []
    for i in range(total_sections):
        refined_text = results_by_index[i]["text"]

        # Deduplicate overlap with previous section's output
        if refined_parts and total_sections > 1:
            refined_text = _deduplicate_overlap(refined_parts[-1], refined_text)

        refined_parts.append(refined_text)

    final_text = "\n\n".join(refined_parts)

    actual_cost = (
        total_input_tokens * CLAUDE_COST_PER_INPUT_TOKEN
        + total_output_tokens * CLAUDE_COST_PER_OUTPUT_TOKEN
    )

    return {
        "refined_text": final_text,
        "mode": mode,
        "sections_processed": total_sections,
        "total_input_chars": len(raw_text),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "actual_cost": round(actual_cost, 4),
    }
