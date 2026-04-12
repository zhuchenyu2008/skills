# Troubleshooting

## Common failures

### Upload page link opens as dead / process disappears right after sending the URL
When launched from an OpenClaw exec-managed session, the foreground upload server can receive `SIGTERM` when the session ends or is reclaimed. Start it with `scripts/start_upload_audio_once_detached.sh` instead, then confirm readiness from the state JSON (and optionally `ss -ltnp | grep <port>`).


### Upload URL returns `not found` even though state says `ready`
The most common cause is a stale upload process still owning the requested port. A fresh state file can contain a new token while the old process is the one actually responding, so every request to the new `upload_url` returns 404.

Fix it in this order:
1. Kill the old listener on that exact port.
2. Restart the upload page on the same requested port.
3. Send a real HTTP GET to the exact `upload_url`.
4. Only share the link after you confirm `200 OK` and the upload-form HTML.

### `Missing required command: docker`
The host does not have Docker in PATH. This skill assumes Docker is available.

### `Repository not found`
Expected runtime path is `<WORKSPACE>/sensevoice-local`.

### Model files missing
Run the wrapper once; it auto-downloads the pre-exported model through `scripts/prepare_model.sh`.

### Long transcription dies in OpenClaw with `SIGKILL` / task ends before completion
If a large audio transcription is launched via an exec-managed background session, the job may be reclaimed or killed before finishing. Re-run it as a detached background job with explicit pid/log/state files, and monitor that state instead of trusting the exec session lifetime.

### Host under memory pressure
This workflow is intentionally capped to `2 CPU / 3GiB RAM / 256 PIDs`. If the server is under pressure, keep those limits or tighten them further via environment variables before running the wrapper.

### Recognition quality is weaker than cloud SOTA
This local model is the stable fallback. It can still drift on numbers, names, and math terms. Report that honestly instead of overclaiming quality.
