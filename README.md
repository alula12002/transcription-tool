# Transcript Studio

A web application for transcribing and refining oral history interviews. Upload audio recordings, transcribe with OpenAI Whisper, refine with Claude, and download polished transcripts.

Built for preserving family stories — the narrator's authentic voice is maintained while transforming raw speech-to-text into readable, organized prose.

## Features

- **Upload** audio files individually or as a zip archive
- **Transcribe** using OpenAI Whisper with prompt chaining for accuracy across chunks
- **Refine** with three AI-powered modes (see below)
- **Download** as `.txt` or `.md` with proper formatting
- **Re-refine** with different modes without re-transcribing
- **Two interfaces**: Streamlit standalone UI or REST API for custom frontends

## Refinement Modes

| Mode | Description | Best For |
|------|-------------|----------|
| **Raw Cleanup** | Adds punctuation and paragraph breaks only. No words changed. | Archival accuracy — when every word matters exactly as spoken |
| **Structured Prose** | Polishes into readable paragraphs while preserving the narrator's voice and phrasing. | Sharing with family, printing, or publishing |
| **Summary** | Condenses into key themes, stories, and takeaways. | Quick reference, cataloging multiple interviews |

## Setup

### 1. Install system dependencies

**macOS** (Homebrew):
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install ffmpeg
```

**Windows** (Chocolatey):
```bash
choco install ffmpeg
```

### 2. Clone and install Python dependencies

```bash
git clone <repo-url>
cd transcription-tool
pip install -r requirements.txt
```

### 3. Configure API keys

Create a `.env` file in the project root:

```
OPENAI_API_KEY=sk-proj-your-openai-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
```

Get keys from:
- OpenAI: https://platform.openai.com/api-keys
- Anthropic: https://console.anthropic.com/

### 4. Run the app

**Option A — Streamlit UI** (standalone, local use — legacy):
```bash
python3 -m streamlit run app.py
```
Opens at http://localhost:8501. Has a 200MB upload limit (Streamlit default). Note: The Streamlit UI (`app.py`) is the original interface, now superseded by the Next.js web app for production use. It's still functional for local testing.

**Option B — FastAPI backend + Next.js frontend** (production):
```bash
python3 -m uvicorn api.main:app --reload
```
Opens at http://localhost:8000. Interactive API docs at http://localhost:8000/docs. No upload size limit.

## API Overview

When running the FastAPI backend, the full flow is:

```
POST /upload/zip          Upload a zip → get job_id
POST /upload/audio        Upload audio files → get job_id
POST /transcribe          Start transcription (async)
GET  /jobs/{job_id}       Poll for status & progress
GET  /estimate/{job_id}   Get refinement cost estimate
POST /refine              Start refinement (async)
GET  /download/{job_id}   Download transcript as text
```

Transcription and refinement run in background threads. Poll `GET /jobs/{job_id}` for progress (0.0 to 1.0) and status (`pending`, `processing`, `completed`, `failed`).

See http://localhost:8000/docs for full interactive API documentation when the server is running.

## Architecture

```
transcription-tool/
├── app.py                 # Streamlit UI (standalone mode)
├── api/
│   ├── main.py            # FastAPI routes
│   ├── schemas.py         # Pydantic request/response models
│   └── jobs.py            # Job store (in-memory; swap for Supabase/Redis)
├── core/
│   ├── chunker.py         # Audio splitting with silence detection
│   ├── transcriber.py     # Whisper API with prompt chaining
│   ├── refiner.py         # Claude API with overlap deduplication
│   └── exporter.py        # .txt and .md file export
├── config/settings.py     # All constants and configuration
├── prompts/               # System prompt templates per mode
├── tests/                 # Full test suite (mocked API calls)
├── output/                # Exported transcripts
└── requirements.txt
```

The `core/` modules are framework-agnostic — they don't depend on Streamlit or FastAPI. Both `app.py` and `api/main.py` are thin wrappers that call into `core/`.

### Deploying with a separate frontend

To use a custom frontend (React/Next.js on Vercel, etc.):

1. Deploy the **FastAPI backend** to Railway, Fly.io, or Render
2. Set `CORS_ORIGINS` env var to your frontend's domain
3. Point your frontend at the API endpoints above
4. Swap `api/jobs.py` from `InMemoryJobStore` to a Supabase/Redis implementation for persistence
5. For large file uploads, upload directly to Supabase Storage / S3 and pass the URL to the API

## Estimated Costs

Rough estimates for a **1-hour interview**:

| Step | Estimated Cost |
|------|---------------|
| Transcription (Whisper) | ~$0.36 |
| Refinement — Raw Cleanup | ~$0.30 |
| Refinement — Structured Prose | ~$0.25 |
| Refinement — Summary | ~$0.08 |
| **Total (transcribe + refine)** | **~$0.44 – $0.66** |

## Running Tests

```bash
python3 -m pytest tests/ -v
```

All API calls are mocked — no keys or network needed for tests. Some chunker tests require ffmpeg.

## Known Limitations

- **No speaker diarization** — Whisper transcribes all speakers as a single stream
- **No streaming** — Refinement completes fully before displaying results
- **English-focused** — Prompt templates are written for English
- **In-memory job store** — Jobs lost on server restart (swap for Supabase/Redis in production)
- **Single worker** — Background threads, not a proper task queue (swap for Celery/Redis in production)

## Future Features

- **Speaker diarization** — Identify and label different speakers
- **Supabase integration** — Persistent storage, auth, direct file uploads
- **Batch processing** — Queue multiple recordings
- **Custom prompt templates** — User-created refinement prompts
- **Timestamp navigation** — Click a paragraph to hear the audio
- **SRT/VTT export** — Subtitle file formats
- **Resume from failure** — Save intermediate state for long recordings
