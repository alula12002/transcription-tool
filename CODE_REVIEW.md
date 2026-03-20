# Code Review: core/chunker.py — Before/After

## Test Results (10/10 passing)

```
✓ _parse_bitrate_kbps          — parses "128k" → 128
✓ calculate_max_chunk_duration  — math correct with 3% safety margin
✓ calculate_max_chunk_duration  — defaults from settings work
✓ chunk_size_guarantee          — 23.51 MB ≤ 24 MB limit
✓ process_zip (valid)           — extracts audio, skips non-audio
✓ process_zip (missing file)    — clear FileNotFoundError
✓ process_zip (invalid zip)     — clear BadZipFile error
✓ _get_duration_ms              — ffprobe returns correct duration
✓ chunk_audio (small file)      — file copied, NOT re-encoded (bytes identical)
✓ chunk_audio (long file)       — 5min file → 7 chunks via ffmpeg stream copy
```

---

## Changes Summary

### 🔴 CRITICAL — Memory usage for large files
| Before | After |
|--------|-------|
| Loaded entire audio into pydub (decompresses to raw PCM in memory — a 1hr mp3 at 128kbps = ~600MB RAM) | Uses ffprobe for metadata, ffmpeg `-c copy` for chunk extraction. Only loads 30-second windows into pydub for silence detection near split points. Peak memory ≈ 30s of PCM regardless of file size. |

### Fix #1 — Redundant file loading
| Before | After |
|--------|-------|
| Each mp3 loaded twice: once in `process_upload` for duration, once in `chunk_audio` for splitting | `chunk_audio` returns `(chunks, duration_ms)`. Duration comes from ffprobe (no audio data loaded). Single source of truth. |

### Fix #2 — Silence detection on small files
| Before | After |
|--------|-------|
| `detect_silence()` called on entire audio even for short files | Early check: if file ≤ max duration, `shutil.copy2()` and return immediately. No silence detection, no pydub load. |

### Fix #3 — Hardcoded bitrate
| Before | After |
|--------|-------|
| `calculate_max_chunk_duration(bitrate_kbps=128, ...)` hardcoded in `process_upload` | Added `_parse_bitrate_kbps()` that parses `AUDIO_BITRATE` setting ("128k" → 128). `calculate_max_chunk_duration()` defaults to parsed value when called with no args. |

### Fix #4 — No zip file validation
| Before | After |
|--------|-------|
| Dove straight into `ZipFile()`, opaque errors on bad input | Validates file exists (`FileNotFoundError`) and is a valid zip (`zipfile.is_zipfile` → `BadZipFile`) before opening. Clear error messages. |

### Fix #5 — Inefficient re-export for single-chunk case
| Before | After |
|--------|-------|
| `audio.export(str(chunk_file), format="mp3", ...)` — loaded entire file into pydub, decoded, re-encoded as mp3 | `shutil.copy2(mp3_path, chunk_file)` — byte-for-byte copy, no decoding or re-encoding. Verified in test: output bytes == input bytes. |

### Fix #6 — Skipped files not returned
| Before | After |
|--------|-------|
| `process_zip` collected skipped files but only returned `extracted_files`. `process_upload` had `"skipped_files": []` with a TODO comment. | `process_zip` returns `(extracted_files, skipped_files)` tuple. `process_upload` passes skipped list through to return dict. |

### Fix #7 — Cleanup errors masking exceptions
| Before | After |
|--------|-------|
| `finally: shutil.rmtree(temp_dir)` — if rmtree fails, it raises and masks the original exception | Wrapped in `try/except OSError`, logs warning but doesn't re-raise. Original exception always propagates cleanly. |

---

## Remaining notes

- **`convert_to_mp3` still uses pydub**: This is intentional — format conversion (wav→mp3, m4a→mp3, etc.) genuinely requires decoding and re-encoding. This runs once per input file, not per chunk, so the memory impact is bounded by individual file size.
- **ffmpeg is required**: The memory-efficient chunking approach depends on ffmpeg/ffprobe being installed. Clear error messages guide the user to install it. Tests gracefully skip when ffmpeg is unavailable.
- **Silence detection uses last gap**: `_find_silence_split_point` picks the last silence gap in the 30-second window (closest to the boundary), which maximizes chunk size and minimizes total chunks.
