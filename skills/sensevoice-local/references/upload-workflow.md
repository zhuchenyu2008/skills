# Upload Workflow

Use this when the user wants to upload a large audio file through a temporary web page.

## Goal

Start a one-shot upload page, send the upload URL to the user, wait for exactly one file, then close the page automatically and continue with transcription.

## Start the page

Preferred wrapper inside OpenClaw / agent exec:

```bash
bash /root/.openclaw/workspace/skills/sensevoice-local/scripts/start_upload_audio_once_detached.sh \
  --port 18793 \
  --output-dir /root/.openclaw/workspace/uploads/sensevoice-local \
  --state-file /root/.openclaw/workspace/uploads/sensevoice-local/state.json
```

Manual foreground debugging only:

```bash
bash /root/.openclaw/workspace/skills/sensevoice-local/scripts/upload_audio_once.sh \
  --port 18793 \
  --output-dir /root/.openclaw/workspace/uploads/sensevoice-local \
  --state-file /root/.openclaw/workspace/uploads/sensevoice-local/state.json
```

If `--public-base` is omitted, the wrapper defaults to `http://172.245.39.168:<port>`.

The detached launcher waits for the state file and then prints the ready JSON with:

- `status: ready`
- `upload_url`
- `port`
- `output_dir`

Before sending the link, verify the process is actually alive if there was any prior failure (for example `ss -ltnp | grep <port>` or a local GET request). Then send `upload_url` to the user right away.

## After upload

On successful upload, the server:

- saves the file into the chosen `output-dir`
- writes final state JSON with `status: uploaded` and `path`
- shuts itself down automatically

On timeout, it writes `status: timeout` and exits.

## Continue the ASR workflow

When `status` becomes `uploaded`, run:

```bash
bash /root/.openclaw/workspace/skills/sensevoice-local/scripts/transcribe_file.sh /path/to/uploaded-audio.mp3
```

Then return the transcript or continue the study-note workflow.

## Notes

- Use a one-shot page only; do not leave the upload port open after success.
- In OpenClaw, avoid depending on the tool-managed exec background session to keep the upload page alive; if that session is terminated, the link dies immediately. Prefer the detached launcher.
- Default behavior is to expose the link as `服务器 IP + 端口 + 随机路径`; override `--public-base` only when you explicitly need a different public入口。
- Keep the skill-level instructions concise; this file holds the operational detail.
