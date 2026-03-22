# Upload Workflow

Use this when the user wants to upload a large audio file through a temporary web page.

## Goal

Start a one-shot upload page, send the upload URL to the user, wait for exactly one file, then close the page automatically and continue with transcription.

## Start the page

Preferred wrapper inside OpenClaw / agent exec:

```bash
bash <WORKSPACE>/skills/sensevoice-local/scripts/start_upload_audio_once_detached.sh \
  --port 18793 \
  --output-dir <WORKSPACE>/uploads/sensevoice-local \
  --state-file <WORKSPACE>/uploads/sensevoice-local/state.json
```

Manual foreground debugging only:

```bash
bash <WORKSPACE>/skills/sensevoice-local/scripts/upload_audio_once.sh \
  --port 18793 \
  --output-dir <WORKSPACE>/uploads/sensevoice-local \
  --state-file <WORKSPACE>/uploads/sensevoice-local/state.json
```

If `--public-base` is omitted, the wrapper defaults to `http://<PUBLIC_IP_OR_HOST>:<port>`.

The detached launcher waits for the state file and then prints the ready JSON with:

- `status: ready`
- `upload_url`
- `port`
- `output_dir`

Before sending the link, do not trust the ready state alone and do not rely only on `ss -ltnp | grep <port>`. Verify the exact final `upload_url` with a real HTTP GET. Only send the link if the request returns `200 OK` and the response body is the upload-form HTML rather than `not found` or another stale response. If verification fails, clear any old listener on that same port, restart on the same requested port, and verify the exact `upload_url` again before replying.

## After upload

On successful upload, the server:

- saves the file into the chosen `output-dir`
- writes final state JSON with `status: uploaded` and `path`
- shuts itself down automatically

On timeout, it writes `status: timeout` and exits.

## Continue the ASR workflow

When `status` becomes `uploaded`, run:

```bash
bash <WORKSPACE>/skills/sensevoice-local/scripts/transcribe_file.sh /path/to/uploaded-audio.mp3
```

Then return the transcript or continue the study-note workflow.

## Notes

- Use a one-shot page only; do not leave the upload port open after success.
- In OpenClaw, avoid depending on the tool-managed exec background session to keep the upload page alive; if that session is terminated, the link dies immediately. Prefer the detached launcher.
- Default behavior is to expose the link as `服务器 IP + 端口 + 随机路径`; override `--public-base` only when you explicitly need a different public入口。
- Keep the skill-level instructions concise; this file holds the operational detail.
