"""Transcript Studio — Streamlit application entry point."""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from config.settings import (
    SUPPORTED_AUDIO_EXTENSIONS,
    REFINEMENT_MODES,
)

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Transcript Studio",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Load environment and validate API keys
# ---------------------------------------------------------------------------
load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

openai_ok = bool(OPENAI_KEY) and OPENAI_KEY != "your_key_here"
anthropic_ok = bool(ANTHROPIC_KEY) and ANTHROPIC_KEY != "your_key_here"

# Audio extensions without the dot, for st.file_uploader's type param
_AUDIO_TYPES = [ext.lstrip(".") for ext in SUPPORTED_AUDIO_EXTENSIONS]

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "upload_result": None,       # dict from chunker.process_upload / process_audio_files
    "upload_fingerprint": None,  # identifies the current upload to detect changes
    "raw_transcript": None,      # full transcript text
    "transcript_result": None,   # full dict from transcriber.transcribe_all
    "transcribing": False,       # True while transcription is running
    "saved_path": None,          # path where raw transcript was saved
    "refined_transcript": None,  # refined transcript text
    "refinement_result": None,   # full dict from refiner.refine_transcript
    "refining": False,           # True while refinement is running
    "total_transcription_cost": 0.0,
    "total_refinement_cost": 0.0,
    "total_minutes_transcribed": 0.0,
    "refinement_count": 0,
}
for key, default in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


def _reset_state():
    """Reset all session state to defaults."""
    for key, default in _DEFAULTS.items():
        st.session_state[key] = default


def _format_duration(total_seconds):
    """Format seconds as H:MM:SS or M:SS depending on length."""
    total_seconds = int(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _upload_fingerprint(files):
    """Create a fingerprint from uploaded file names + sizes to detect changes."""
    if not files:
        return None
    if not isinstance(files, list):
        files = [files]
    parts = sorted(f"{f.name}:{f.size}" for f in files)
    return "|".join(parts)


# ---------------------------------------------------------------------------
# Sidebar — API key status + session stats
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("API Keys")
    if openai_ok:
        st.success("OpenAI API key loaded", icon="✅")
    else:
        st.error("OpenAI API key missing", icon="❌")

    if anthropic_ok:
        st.success("Anthropic API key loaded", icon="✅")
    else:
        st.error("Anthropic API key missing", icon="❌")

    st.divider()

    st.header("Session Stats")
    mins = st.session_state.total_minutes_transcribed
    st.metric("Minutes transcribed", f"{mins:.1f}")
    st.metric("Refinements run", st.session_state.refinement_count)
    total_cost = (
        st.session_state.total_transcription_cost
        + st.session_state.total_refinement_cost
    )
    st.metric("Estimated total cost", f"${total_cost:.4f}")

    st.divider()
    st.caption("Keys are loaded from the .env file in the project root.")

# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
st.title("Transcript Studio")
st.subheader("Upload audio recordings, transcribe them, and refine the output.")

# =====================================================================
# Step 1 — Upload
# =====================================================================
st.header("Step 1: Upload")

tab_zip, tab_audio = st.tabs(["Upload Zip", "Upload Audio Files"])

# --- Zip upload tab ---
with tab_zip:
    uploaded_zip = st.file_uploader(
        "Upload a .zip file containing audio recordings",
        type=["zip"],
        key="zip_uploader",
    )

# --- Audio files upload tab ---
with tab_audio:
    uploaded_audio = st.file_uploader(
        "Upload one or more audio files",
        type=_AUDIO_TYPES,
        accept_multiple_files=True,
        key="audio_uploader",
    )

# Determine which upload is active
active_files = None
upload_mode = None

if uploaded_zip is not None:
    active_files = uploaded_zip
    upload_mode = "zip"
elif uploaded_audio:
    active_files = uploaded_audio
    upload_mode = "audio"

if active_files is not None:
    # Build a fingerprint to detect new/changed uploads
    if upload_mode == "zip":
        fingerprint = _upload_fingerprint(active_files)
        display_name = active_files.name
    else:
        fingerprint = _upload_fingerprint(active_files)
        names = [f.name for f in active_files]
        display_name = names[0] if len(names) == 1 else f"{len(names)} audio files"

    # Detect new upload → reset state and process
    if fingerprint != st.session_state.upload_fingerprint:
        from core.chunker import cleanup_temp_dir
        cleanup_temp_dir()

        _reset_state()
        st.session_state.upload_fingerprint = fingerprint

        with st.spinner("Processing audio files..."):
            try:
                if upload_mode == "zip":
                    # Write zip to temp file and process
                    with tempfile.NamedTemporaryFile(
                        suffix=".zip", delete=False
                    ) as tmp:
                        tmp.write(active_files.getvalue())
                        tmp_path = tmp.name

                    try:
                        from core.chunker import process_upload
                        result = process_upload(tmp_path, cleanup=False)
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)

                else:
                    # Write each audio file to temp dir and process
                    staging_dir = os.path.join("temp_audio", "staged")
                    os.makedirs(staging_dir, exist_ok=True)

                    staged_paths = []
                    for uf in active_files:
                        dest = os.path.join(staging_dir, uf.name)
                        with open(dest, "wb") as f:
                            f.write(uf.getvalue())
                        staged_paths.append(dest)

                    from core.chunker import process_audio_files
                    result = process_audio_files(staged_paths, cleanup=False)

                st.session_state.upload_result = result

            except Exception as e:
                st.error(f"Failed to process upload: {e}")

    # Display summary card if we have results
    result = st.session_state.upload_result
    if result is not None:
        if result["num_files_found"] == 0:
            st.warning(
                "No audio files found. "
                "Supported formats: mp3, m4a, wav, ogg, flac, webm, aac, wma."
            )
            if result["skipped_files"]:
                with st.expander("Skipped files"):
                    for f in result["skipped_files"]:
                        st.text(f)
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Audio files", result["num_files_found"])
            col2.metric("Total duration", _format_duration(result["total_duration_seconds"]))
            col3.metric("Chunks", result["num_chunks"])
            col4.metric("Est. cost", f"${result['estimated_cost']:.2f}")

            if result["skipped_files"]:
                with st.expander(f"{len(result['skipped_files'])} non-audio files skipped"):
                    for f in result["skipped_files"]:
                        st.text(f)

            # =================================================================
            # Step 2 — Transcribe
            # =================================================================
            st.header("Step 2: Transcribe")

            if not openai_ok:
                st.warning(
                    "OpenAI API key is missing. Add your key to the .env file "
                    "and restart the app to enable transcription."
                )

            # Show transcript if already done
            if st.session_state.raw_transcript is not None:
                _show_transcript = True
            else:
                _show_transcript = False

                transcribe_clicked = st.button(
                    "Transcribe",
                    disabled=not openai_ok,
                    type="primary",
                )

                if transcribe_clicked and not st.session_state.transcribing:
                    st.session_state.transcribing = True

                    from core.transcriber import transcribe_all, save_raw_transcript

                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    def _progress(current, total):
                        progress_bar.progress(current / total)
                        status_text.text(f"Processing chunk {current} of {total}")

                    try:
                        transcript_result = transcribe_all(
                            result["chunk_paths"],
                            progress_callback=_progress,
                        )
                        st.session_state.transcript_result = transcript_result
                        st.session_state.raw_transcript = transcript_result["full_text"]

                        # Track stats
                        duration_min = result["total_duration_seconds"] / 60.0
                        st.session_state.total_minutes_transcribed += duration_min
                        st.session_state.total_transcription_cost += transcript_result["estimated_cost"]

                        # Auto-save to output/
                        saved = save_raw_transcript(
                            transcript_result["full_text"],
                            display_name,
                        )
                        st.session_state.saved_path = saved

                        # Chunk files no longer needed
                        from core.chunker import cleanup_temp_dir
                        cleanup_temp_dir()

                        progress_bar.progress(1.0)
                        status_text.text("Transcription complete!")
                        _show_transcript = True

                    except Exception as e:
                        st.error(f"Transcription failed: {e}")
                    finally:
                        st.session_state.transcribing = False

            if _show_transcript and st.session_state.transcript_result is not None:
                tr = st.session_state.transcript_result

                # Stats
                col1, col2 = st.columns(2)
                col1.metric(
                    "Processing time",
                    f"{tr['processing_time_seconds']:.1f}s",
                )
                col2.metric("Actual cost", f"${tr['estimated_cost']:.2f}")

                if st.session_state.saved_path:
                    st.caption(f"Raw transcript saved to: {st.session_state.saved_path}")

                # Transcript display
                st.text_area(
                    "Raw Transcript",
                    value=st.session_state.raw_transcript,
                    height=400,
                    disabled=True,
                )

                # Download button
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_name = Path(display_name).stem
                st.download_button(
                    "Download Raw Transcript",
                    data=st.session_state.raw_transcript,
                    file_name=f"{base_name}_raw_{timestamp}.txt",
                    mime="text/plain",
                )

                # =============================================================
                # Step 3 — Refine
                # =============================================================
                st.header("Step 3: Refine")

                if not anthropic_ok:
                    st.warning(
                        "Anthropic API key is missing. Add your key to the .env file "
                        "and restart the app to enable refinement."
                    )

                # Mode selection — map display names back to keys
                mode_keys = list(REFINEMENT_MODES.keys())
                mode_labels = list(REFINEMENT_MODES.values())

                selected_label = st.radio(
                    "Refinement mode",
                    options=mode_labels,
                    disabled=not anthropic_ok,
                )
                selected_mode = mode_keys[mode_labels.index(selected_label)]

                # Additional user instructions
                user_instructions = st.text_input(
                    "Additional context (optional)",
                    placeholder="e.g., My father's name is Joseph. He grew up in Silver Spring, Maryland.",
                    disabled=not anthropic_ok,
                )

                # Cost estimate
                from core.refiner import estimate_refinement_cost
                cost_est = estimate_refinement_cost(
                    st.session_state.raw_transcript, mode=selected_mode
                )
                st.caption(
                    f"Estimated refinement cost: ${cost_est['estimated_cost']:.4f} "
                    f"(~{cost_est['estimated_input_tokens']:,} input tokens, "
                    f"~{cost_est['estimated_output_tokens']:,} output tokens)"
                )

                # Refine button
                refine_clicked = st.button(
                    "Refine Transcript",
                    disabled=not anthropic_ok,
                    type="primary",
                )

                if refine_clicked and not st.session_state.refining:
                    st.session_state.refining = True

                    from core.refiner import refine_transcript

                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    def _refine_progress(current, total):
                        progress_bar.progress(current / total)
                        status_text.text(
                            f"Refining section {current} of {total}..."
                        )

                    try:
                        refinement_result = refine_transcript(
                            st.session_state.raw_transcript,
                            mode=selected_mode,
                            user_instructions=user_instructions or None,
                            progress_callback=_refine_progress,
                        )
                        st.session_state.refined_transcript = refinement_result["refined_text"]
                        st.session_state.refinement_result = refinement_result

                        # Track stats
                        st.session_state.refinement_count += 1
                        st.session_state.total_refinement_cost += refinement_result["actual_cost"]

                        progress_bar.progress(1.0)
                        status_text.text("Refinement complete!")

                    except Exception as e:
                        st.error(f"Refinement failed: {e}")
                        st.info("Your raw transcript is still safe above.")
                    finally:
                        st.session_state.refining = False

                # Show results if we have a refined transcript
                if st.session_state.refined_transcript is not None:
                    ref = st.session_state.refinement_result

                    st.divider()

                    # Refinement stats
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Mode", REFINEMENT_MODES.get(ref["mode"], ref["mode"]))
                    col2.metric("Sections processed", ref["sections_processed"])
                    col3.metric("Actual cost", f"${ref['actual_cost']:.4f}")

                    # Toggle between raw and refined views
                    view = st.radio(
                        "View",
                        options=["Refined Transcript", "Raw Transcript"],
                        horizontal=True,
                    )

                    if view == "Refined Transcript":
                        st.text_area(
                            "Refined Transcript",
                            value=st.session_state.refined_transcript,
                            height=400,
                            disabled=True,
                        )
                    else:
                        st.text_area(
                            "Raw Transcript",
                            value=st.session_state.raw_transcript,
                            height=400,
                            disabled=True,
                            key="raw_transcript_view_toggle",
                        )

                    # Download buttons
                    st.subheader("Download")
                    from core.exporter import export_transcript

                    dl_col1, dl_col2, dl_col3, dl_col4 = st.columns(4)

                    with dl_col1:
                        st.download_button(
                            "Refined (.txt)",
                            data=st.session_state.refined_transcript,
                            file_name=f"{base_name}_{ref['mode']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            mime="text/plain",
                        )
                    with dl_col2:
                        # Build markdown content inline for download
                        mode_display = REFINEMENT_MODES.get(ref["mode"], ref["mode"])
                        md_content = f"# Transcript: {base_name} — {mode_display}\n\n"
                        sections = st.session_state.refined_transcript.split("\n\n\n")
                        md_content += "\n\n---\n\n".join(sections)
                        st.download_button(
                            "Refined (.md)",
                            data=md_content,
                            file_name=f"{base_name}_{ref['mode']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                            mime="text/markdown",
                        )
                    with dl_col3:
                        st.download_button(
                            "Raw (.txt)",
                            data=st.session_state.raw_transcript,
                            file_name=f"{base_name}_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            mime="text/plain",
                            key="download_raw_txt",
                        )
                    with dl_col4:
                        raw_md = f"# Transcript: {base_name} — Raw\n\n"
                        raw_md += st.session_state.raw_transcript
                        st.download_button(
                            "Raw (.md)",
                            data=raw_md,
                            file_name=f"{base_name}_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                            mime="text/markdown",
                            key="download_raw_md",
                        )

                    # Save to disk buttons
                    with st.expander("Save to output/ directory"):
                        save_col1, save_col2 = st.columns(2)
                        with save_col1:
                            if st.button("Save refined .txt to disk"):
                                path = export_transcript(
                                    st.session_state.refined_transcript,
                                    display_name,
                                    ref["mode"],
                                    format="txt",
                                )
                                st.success(f"Saved: {path}")
                        with save_col2:
                            if st.button("Save refined .md to disk"):
                                path = export_transcript(
                                    st.session_state.refined_transcript,
                                    display_name,
                                    ref["mode"],
                                    format="md",
                                )
                                st.success(f"Saved: {path}")
