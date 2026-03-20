# Transcript Studio — Full Project Deployment Guide

## Project Vision

Transcript Studio is a local web application for transcribing and refining audio recordings. The primary use case is oral history interviews — a son preserving his father's stories. The tool takes uploaded zip files of audio recordings, chunks them for the Whisper API, transcribes them, and then offers AI-powered refinement that preserves the narrator's authentic voice while transforming raw transcripts into polished, usable formats.

## Architecture Overview

```
User uploads .zip of audio files
        │
        ▼
   ┌─────────────┐
   │   CHUNKER    │  Extract → Convert to mp3 mono 128kbps → Split at silence gaps
   │ chunker.py   │  Keeps chunks under 24MB for Whisper API limit
   └──────┬──────┘
          │  ordered list of chunk file paths
          ▼
   ┌──────────────┐
   │ TRANSCRIBER   │  Send chunks sequentially to OpenAI Whisper API
   │transcriber.py │  Assemble full transcript with adjusted timestamps
   └──────┬───────┘
          │  raw transcript text + timestamped segments
          ▼
   ┌─────────────┐
   │   REFINER    │  Send transcript to Claude API with selected prompt template
   │  refiner.py  │  Handles long transcripts by splitting into overlapping sections
   └──────┬──────┘
          │  refined transcript text
          ▼
   ┌─────────────┐
   │  EXPORTER    │  Save as .txt or .md with proper naming convention
   │ exporter.py  │  Delivers downloadable files through Streamlit UI
   └─────────────┘
```

## Tech Stack

| Component        | Technology                          | Purpose                              |
|-----------------|-------------------------------------|--------------------------------------|
| Language         | Python 3.11+                       | All backend logic                    |
| UI Framework     | Streamlit                          | Local web interface                  |
| Transcription    | OpenAI Whisper API (whisper-1)     | Speech-to-text                       |
| Refinement       | Anthropic Claude API (claude-sonnet-4-20250514) | Transcript cleanup & transformation |
| Audio Processing | pydub + ffmpeg                     | Format conversion and chunking       |
| Config           | python-dotenv                      | API key management                   |

## Project Structure

```
transcription-tool/
├── .env                     # API keys (gitignored)
├── .gitignore
├── README.md
├── requirements.txt
├── app.py                   # Streamlit entry point — UI and page routing
├── core/
│   ├── __init__.py
│   ├── chunker.py           # Unzip, convert, chunk audio files
│   ├── transcriber.py       # Whisper API integration
│   ├── refiner.py           # Claude API integration with prompt templates
│   └── exporter.py          # Format and save output files
├── config/
│   ├── __init__.py
│   └── settings.py          # All constants and configuration
├── prompts/
│   ├── raw_cleanup.txt      # Minimal cleanup prompt
│   ├── structured_prose.txt # Editorial prose prompt
│   └── summary.txt          # Condensed summary prompt
├── output/                  # Transcripts and refined outputs saved here
│   └── .gitkeep
└── tests/
    ├── __init__.py
    ├── test_chunker.py
    ├── test_transcriber.py
    └── test_refiner.py
```

## Key Design Decisions

### Chunking Strategy
- Audio converted to mp3 mono 128kbps to minimize file size
- Chunks capped at 24MB (1MB buffer below Whisper's 25MB limit), plus 3% safety margin for mp3 encoding overhead
- Splits prefer silence gaps (700ms minimum at -40dBFS) to avoid cutting mid-sentence
- If no silence found within 30 seconds of the boundary, splits at the hard boundary
- Memory-efficient: uses ffmpeg subprocess for splitting large files, not in-memory pydub operations

### Transcript Handling
- Raw transcript is the permanent asset — always saved automatically, never modified
- Timestamps adjusted across chunks by cumulative offset so they're accurate for the full recording
- Refinement operates on a copy, never touches the raw transcript

### Refinement Architecture
- Long transcripts split into overlapping sections (~80,000 chars per section, 500 char overlap) to stay within Claude's context window
- Each refinement mode is a separate prompt template file in prompts/ — easy to add new modes
- User can provide additional context (names, places, dates) via free-text input that gets appended to the prompt
- User can re-refine with different modes without re-transcribing

### Three MVP Refinement Modes

1. **Raw Cleanup**: Punctuation, paragraphs, speaker labels. Everything else verbatim including filler words and fragments.
2. **Structured Prose**: Polished readable narrative. Filler removed, sentences smoothed, organized by topic with section headers. Narrator's voice, vocabulary, and dialect fully preserved.
3. **Summary**: Third-person condensed account. Key stories, themes, biographical details. ~10-15% of original length. Ends with topic list.

## Configuration Reference (config/settings.py)

```
WHISPER_MODEL = "whisper-1"
CLAUDE_MODEL = "claude-sonnet-4-20250514"
WHISPER_COST_PER_MINUTE = 0.006
MAX_CHUNK_SIZE_MB = 24
AUDIO_BITRATE = "128k"
SILENCE_THRESH_DB = -40
MIN_SILENCE_LEN_MS = 700
SPLIT_SEARCH_WINDOW_MS = 30000
MAX_TRANSCRIPT_CHARS_PER_CALL = 80000
OVERLAP_CHARS = 500
SUPPORTED_AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.ogg', '.flac', '.webm', '.aac', '.wma'}
```

## Cost Estimates (for 15 hours of audio)

| Stage          | Cost         | Notes                                    |
|---------------|-------------|------------------------------------------|
| Transcription  | ~$5.40      | 15 hrs × 60 min × $0.006/min            |
| Refinement     | ~$3–5       | Depends on transcript length and mode    |
| Re-refinement  | ~$1–2 each  | Only the Claude API call, no re-transcription |
| **Total MVP**  | **~$10–12** | For full transcription + 2-3 refinement passes |

## Setup Instructions

### Prerequisites
- Python 3.11 or higher
- ffmpeg installed on the system
  - macOS: `brew install ffmpeg`
  - Ubuntu: `sudo apt install ffmpeg`
  - Windows: `choco install ffmpeg`

### Installation
```bash
git clone <repo-url>
cd transcription-tool
pip install -r requirements.txt
```

### API Keys
Create a `.env` file in the project root with your actual keys:
```
OPENAI_API_KEY=sk-your-openai-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
```
API keys are configured and validated at app startup.

### Running the App
```bash
streamlit run app.py
```
The app opens in your browser at http://localhost:8501

## Build Phases

The project is built incrementally in 7 phases (plus a 2.5 fix phase). Each phase is a discrete prompt for Claude Code. Each phase includes built-in testing and review.

| Phase | What It Builds                        | Status      |
|-------|--------------------------------------|-------------|
| 1     | Project scaffolding & structure       | ✅ Complete  |
| 2     | Audio chunker module                  | ✅ Complete  |
| 2.5   | Chunker fixes from code review       | ✅ Complete  |
| 3     | Transcriber module                    | ✅ Complete  |
| 4     | Streamlit UI: upload & transcribe     | ✅ Complete  |
| 5     | Refiner module & prompt templates     | 🔲 Pending   |
| 6     | Refinement UI & exporter              | 🔲 Pending   |
| 7     | Final polish, tests, docs, git repo  | 🔲 Pending   |

## Error Handling Philosophy

- Transcription failure should never lose work — raw transcript is saved after each chunk
- Refinement failure should never lose the raw transcript
- Empty or invalid zips produce clear error messages, not crashes
- API costs are shown BEFORE processing starts
- Retry with exponential backoff on transient API failures (3 attempts)

## Future Expansion (not in MVP, but architecture supports)

### Near-term additions
- Additional refinement modes: podcast script, blog post, timeline, Q&A format
- Export to .docx and .pdf
- Speaker diarization (label Interviewer vs Narrator automatically)
- Full-text search across all transcripts in output/

### Medium-term additions
- Batch processing: queue multiple zip files
- Cost tracking: persistent log across sessions
- Swap transcription backends (Deepgram, AssemblyAI, local Whisper)
- Resume interrupted transcription from the last successful chunk

### Long-term vision
- Generate podcast episodes from interviews
- Build a website/blog from the stories
- Create a searchable family history archive

## Testing Strategy

- Each module has its own test file in tests/
- Tests mock API calls — no real API costs during testing
- Chunker tests use pydub-generated silent audio, not real recordings
- Run all tests: `python -m pytest tests/ -v`
- Manual testing with short (30-second) audio clips to minimize API costs during development

## Known Limitations (MVP)

- English language only (hardcoded in transcriber, configurable later)
- No speaker diarization — speaker labels in refinement are Claude's best guess from context
- Sequential chunk processing (no parallelism)
- No resume capability — if transcription fails mid-way, the completed chunks' text is saved but you'd need to re-run from the beginning in the UI
- Refinement quality depends on transcript quality — garbage in, garbage out
- No persistent session — closing the browser tab loses the current session state (transcripts are still saved to disk)
