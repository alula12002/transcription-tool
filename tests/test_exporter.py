"""Tests for core/exporter.py."""

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from core.exporter import export_transcript


class TestExportTranscript:
    """Tests for the export_transcript function."""

    def setup_method(self):
        """Create a temp output directory for each test."""
        self._tmp = tempfile.mkdtemp()
        self._patch = mock.patch(
            "core.exporter._OUTPUT_DIR", Path(self._tmp)
        )
        self._patch.start()

    def teardown_method(self):
        """Clean up temp files."""
        self._patch.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_export_txt_basic(self):
        text = "Hello world.\n\nThis is a transcript."
        path = export_transcript(text, "interview.mp3", "raw_cleanup", format="txt")

        assert path.endswith(".txt")
        assert "interview_raw_cleanup_" in path
        assert os.path.exists(path)
        assert Path(path).read_text(encoding="utf-8") == text

    def test_export_md_has_header(self):
        text = "Some refined text."
        path = export_transcript(text, "session1.wav", "structured_prose", format="md")

        content = Path(path).read_text(encoding="utf-8")
        assert content.startswith("# Transcript: session1")
        assert "Structured Prose" in content
        assert "Some refined text." in content

    def test_export_md_section_breaks(self):
        text = "Part one.\n\n\nPart two.\n\n\nPart three."
        path = export_transcript(text, "test.mp3", "summary", format="md")

        content = Path(path).read_text(encoding="utf-8")
        assert "---" in content
        assert "Part one." in content
        assert "Part two." in content

    def test_export_filename_format(self):
        path = export_transcript("text", "my file.mp3", "raw_cleanup", format="txt")
        filename = os.path.basename(path)
        # Should be: my file_raw_cleanup_YYYYMMDD_HHMMSS.txt
        assert filename.startswith("my file_raw_cleanup_")
        assert filename.endswith(".txt")
        # Timestamp portion should be 15 chars: YYYYMMDD_HHMMSS
        timestamp_part = filename.replace("my file_raw_cleanup_", "").replace(".txt", "")
        assert len(timestamp_part) == 15

    def test_export_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported format"):
            export_transcript("text", "test.mp3", "raw_cleanup", format="pdf")

    def test_export_creates_output_dir(self):
        import shutil
        shutil.rmtree(self._tmp)
        assert not os.path.exists(self._tmp)

        path = export_transcript("text", "test.mp3", "raw_cleanup", format="txt")
        assert os.path.exists(path)

    def test_export_default_format_is_txt(self):
        path = export_transcript("text", "test.mp3", "raw_cleanup")
        assert path.endswith(".txt")
