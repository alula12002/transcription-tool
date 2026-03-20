"""Export refined transcripts to text and markdown files.

Handles file naming, output directory management, and format conversion.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import REFINEMENT_MODES

# Output directory at project root
_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def export_transcript(
    text: str,
    original_filename: str,
    mode: str,
    format: str = "txt",
) -> str:
    """Export a transcript to a file in the output/ directory.

    Args:
        text: The transcript text to export.
        original_filename: The name of the original audio file (used in naming).
        mode: The refinement mode key (e.g. 'raw_cleanup', 'structured_prose').
        format: Output format — 'txt' or 'md'.

    Returns:
        The full file path of the exported file.

    Raises:
        ValueError: If format is not 'txt' or 'md'.
    """
    if format not in ("txt", "md"):
        raise ValueError(f"Unsupported format '{format}'. Use 'txt' or 'md'.")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_name = Path(original_filename).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{base_name}_{mode}_{timestamp}.{format}"
    filepath = _OUTPUT_DIR / filename

    if format == "md":
        mode_display = REFINEMENT_MODES.get(mode, mode)
        content = f"# Transcript: {base_name} — {mode_display}\n\n"
        # Replace section breaks (triple newlines or more) with markdown horizontal rules
        sections = text.split("\n\n\n")
        content += "\n\n---\n\n".join(sections)
    else:
        content = text

    filepath.write_text(content, encoding="utf-8")
    return str(filepath)
