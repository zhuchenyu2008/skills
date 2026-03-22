---
name: sensevoice-local
description: Use the locally deployed `sensevoice-local` CPU ASR on this server to transcribe Chinese-heavy class recordings and large audio files. Also use when the user wants a temporary one-shot web upload page for a large audio file before transcription, especially when Telegram audio/file delivery is unreliable or limited by size.
---

Use the bundled wrappers instead of re-deriving Docker commands or ad-hoc upload servers.

## Quick Start

- Basic transcription: `bash <WORKSPACE>/skills/sensevoice-local/scripts/transcribe_file.sh /path/to/audio.mp3`
- Chinese transcription: `bash <WORKSPACE>/skills/sensevoice-local/scripts/transcribe_file.sh --language zh /path/to/audio.mp3`
- One-shot upload page（OpenClaw / long-lived link）: `bash <WORKSPACE>/skills/sensevoice-local/scripts/start_upload_audio_once_detached.sh --port 18793 --state-file <WORKSPACE>/uploads/sensevoice-local/state.json`

## Workflow

1. If the user already provided a readable local audio path, use `scripts/transcribe_file.sh` directly for short/manual runs.
2. In OpenClaw/agent exec, if the audio is large or transcription may run longer than the tool session, launch transcription as a detached background job you can monitor via pid/log/state files; do not rely on an exec-managed background session for long ASR runs.
3. If the user wants to upload a large file through the browser, read `references/upload-workflow.md`, then start the one-shot upload page with `scripts/start_upload_audio_once_detached.sh` when running inside OpenClaw/agent exec. Use the non-detached wrapper only for manual local debugging.
4. Wait for the launcher to print/write the ready JSON. Do not trust `ready` alone, and do not trust only a listening port. Before sending the link, send a real HTTP GET to the exact final `upload_url` and require HTTP 200 plus the upload-form HTML in the response body.
5. After one successful upload, let the upload server auto-close, then feed the uploaded file into transcription using the same detached-monitorable pattern for long files.
6. Return the transcript directly, or continue any downstream note-processing workflow.
7. If anything fails, read `references/troubleshooting.md` and then retry only the minimal fix.

## Operational Notes

- Runtime path: `<WORKSPACE>/sensevoice-local`
- Wrapper delegates to the stable local CLI instead of touching model internals.
- Default upload directory: `<WORKSPACE>/uploads/sensevoice-local`
- Default public upload base: `http://<PUBLIC_IP_OR_HOST>:<port>`
- Default runtime limits are hard-capped in the wrapper: `2 CPU / 3GiB RAM / 256 PIDs`
- This is a local quality-first fallback, not a top-tier cloud ASR; numbers and terms can still drift.
- The upload page is single-use by design; do not keep it running after success.
- In OpenClaw, do not rely on an exec-managed foreground/background session for the upload page link; spawn it detached and read the state JSON, otherwise the process may receive SIGTERM before the user opens the page.
- If the user explicitly specifies a port, keep that port. If verification fails because of a stale process or token mismatch, clear the old listener on that same port, restart on the same requested port, and re-verify before replying.
- The same rule applies to long ASR jobs: large-audio transcription should run detached with log/state files, otherwise the job may be killed before completion.

## Output Conventions

- Default: send only the final transcript, lightly cleaned for readability if needed.
- Upload mode: tell the user the temporary link, mention that it closes automatically after one upload, and report timeout clearly if no file arrives.
- Unless the user asked for debugging, avoid noisy per-segment logs in chat.
