---
name: sensevoice-local
description: Use the locally deployed `sensevoice-local` CPU ASR on this server to transcribe Chinese-heavy class recordings and large audio files. Also use when the user wants a temporary one-shot web upload page for a large audio file before transcription, especially when Telegram audio/file delivery is unreliable or limited by size.
---

Use the bundled wrappers instead of re-deriving Docker commands or ad-hoc upload servers.

## Quick Start

- Basic transcription: `bash skills/sensevoice-local/scripts/transcribe_file.sh /path/to/audio.mp3`
- Chinese transcription: `bash skills/sensevoice-local/scripts/transcribe_file.sh --language zh /path/to/audio.mp3`
- One-shot upload page: `bash skills/sensevoice-local/scripts/upload_audio_once.sh --port 18793 --state-file ./uploads/sensevoice-local/state.json`

## Workflow

1. If the user already provided a readable local audio path, use `scripts/transcribe_file.sh` directly.
2. If the user wants to upload a large file through the browser, read `references/upload-workflow.md`, then start the one-shot upload page with `scripts/upload_audio_once.sh`.
3. Send the generated `upload_url` to the user immediately.
4. After one successful upload, let the upload server auto-close, then feed the uploaded file into `scripts/transcribe_file.sh`.
5. Return the transcript directly, or continue any downstream note-processing workflow.
6. If anything fails, read `references/troubleshooting.md` and then retry only the minimal fix.

## Operational Notes

- Runtime path: set `SENSEVOICE_RUNTIME_DIR` to your local SenseVoice runtime (default: `/opt/sensevoice-local`).
- Wrapper delegates to the stable local CLI instead of touching model internals.
- Default upload directory: `./uploads/sensevoice-local` (override with `SENSEVOICE_UPLOAD_DIR`).
- Default public upload base: `http://<PUBLIC_HOST>:<port>` (override with `PUBLIC_UPLOAD_HOST` or `--public-base`).
- Default runtime limits are hard-capped in the wrapper: `2 CPU / 3GiB RAM / 256 PIDs`
- This is a local quality-first fallback, not a top-tier cloud ASR; numbers and terms can still drift.
- The upload page is single-use by design; do not keep it running after success.

## Output Conventions

- Default: send only the final transcript, lightly cleaned for readability if needed.
- Upload mode: tell the user the temporary link, mention that it closes automatically after one upload, and report timeout clearly if no file arrives.
- Unless the user asked for debugging, avoid noisy per-segment logs in chat.
