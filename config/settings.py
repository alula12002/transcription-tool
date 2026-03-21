"""Application-wide constants and configuration settings.

Environment variables are loaded here (once) so that any module
importing from config.settings gets .env values automatically.
"""

from dotenv import load_dotenv

load_dotenv()

# OpenAI Whisper settings
WHISPER_MODEL = "whisper-1"
WHISPER_COST_PER_MINUTE = 0.006

# Anthropic Claude settings (pricing as of March 2025 — verify at https://docs.anthropic.com/en/docs/about-claude/models)
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_COST_PER_INPUT_TOKEN = 3.00 / 1_000_000   # $3.00 per 1M input tokens
CLAUDE_COST_PER_OUTPUT_TOKEN = 15.00 / 1_000_000  # $15.00 per 1M output tokens

# Audio chunking settings
MAX_CHUNK_SIZE_MB = 24
AUDIO_BITRATE = "128k"
SILENCE_THRESH_DB = -40
MIN_SILENCE_LEN_MS = 700
SPLIT_SEARCH_WINDOW_MS = 30000

# Transcript processing settings
MAX_TRANSCRIPT_CHARS_PER_CALL = 80000
OVERLAP_CHARS = 500

# Supported file types
SUPPORTED_AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.ogg', '.flac', '.webm', '.aac', '.wma'}

# Refinement modes
REFINEMENT_MODES = {
    'raw_cleanup': 'Raw Cleanup (punctuation & paragraphs only)',
    'structured_prose': 'Structured Prose (polished, voice preserved)',
    'summary': 'Summary (condensed themes & stories)',
}
