# Transcript Studio

A local web application for transcribing and refining oral history interviews. Upload audio recordings, transcribe with OpenAI Whisper, refine with Claude, and download polished transcripts.

Built for preserving family stories — the narrator's authentic voice is maintained while transforming raw speech-to-text into readable, organized prose.

## Features

- **Upload** audio files individually or as a zip archive
- **Transcribe** using OpenAI Whisper with prompt chaining for accuracy across chunks
- **Refine** with three AI-powered modes (see below)
- **Download** as `.txt` or `.md` with proper formatting
- **Re-refine** with different modes without re-transcribing
- **Cost tracking** in the sidebar for full session visibility

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

```bash
streamlit run app.py
```

Opens in your browser at http://localhost:8501.

## Estimated Costs

Costs depend on audio length and refinement mode. Rough estimates for a **1-hour interview**:

| Step | Estimated Cost |
|------|---------------|
| Transcription (Whisper) | ~$0.36 |
| Refinement — Raw Cleanup | ~$0.30 |
| Refinement — Structured Prose | ~$0.25 |
| Refinement — Summary | ~$0.08 |
| **Total (transcribe + refine)** | **~$0.44 – $0.66** |

Actual costs depend on speech density and API pricing at time of use.

## Project Structure

```
transcription-tool/
├── app.py                 # Streamlit web UI
├── config/settings.py     # All constants and configuration
├── core/
│   ├── chunker.py         # Audio splitting with silence detection
│   ├── transcriber.py     # Whisper API with prompt chaining
│   ├── refiner.py         # Claude API with overlap deduplication
│   └── exporter.py        # .txt and .md file export
├── prompts/               # System prompt templates per mode
├── tests/                 # Full test suite (mocked API calls)
├── output/                # Exported transcripts
└── requirements.txt
```

## Running Tests

```bash
python3 -m pytest tests/ -v
```

All API calls are mocked — no keys or network needed for tests. Some chunker tests require ffmpeg to be installed.

## Known Limitations

- **No speaker diarization** — Whisper transcribes all speakers as a single stream. Multi-speaker interviews show as one continuous block.
- **Max file size** — Individual audio files are chunked to stay under Whisper's 25MB limit. Very long recordings (5+ hours) work but take longer.
- **No streaming** — Refinement processes the full transcript before displaying results. Long transcripts may take a minute or two.
- **English-focused** — Prompt templates are written for English. Whisper supports other languages but refinement quality may vary.
- **No persistent storage** — Session state resets when the browser tab is closed. Use the download/export buttons to save your work.
- **Single user** — Designed for local use. No authentication or multi-user support.

## Future Features

- **Speaker diarization** — Identify and label different speakers in the transcript
- **Batch processing** — Queue multiple recordings and process overnight
- **Custom prompt templates** — Let users create and save their own refinement prompts
- **Timestamp navigation** — Click a paragraph to hear the corresponding audio
- **SRT/VTT export** — Subtitle file formats for video use
- **Cloud deployment** — One-click deploy to Streamlit Cloud with secrets management
- **Resume from failure** — Save intermediate state so a crash doesn't lose progress on long recordings
