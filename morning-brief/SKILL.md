---
name: morning-brief
description: Generate and deliver a daily Chinese “早报” voice message for a Telegram forum topic by fetching the full day’s weather forecast from a fixed ChatGPT share link, fetching the latest RSS-AI daily report, concatenating them mostly verbatim (no rewriting), running local TTS (piper-http) + ffmpeg Opus conversion, and posting into a specified Telegram group topic at a scheduled time (e.g., 05:10 Asia/Shanghai).
---

# Morning Brief

Use the bundled script to produce a **verbatim** daily morning brief (weather + RSS-AI daily report) and post it as a Telegram **voice** message to a specific **forum topic**.

## Workflow

1. Prepare a config JSON (see `--init-config` output format in the script).
2. Run the script once manually to validate extraction + TTS + Telegram delivery.
3. Schedule it (cron) for `05:10` with `CRON_TZ=Asia/Shanghai`.

## Script

- Main entry: `scripts/morning_brief.py`

Examples:

```bash
python3 scripts/morning_brief.py --config <WORKSPACE>/automation/morning/config.json --dry-run
python3 scripts/morning_brief.py --config <WORKSPACE>/automation/morning/config.json
```

Notes:

- Weather extraction must include the **full “today” section** from the share page. The script searches for today’s date and extracts until the next date header (or end).
- Content policy: **do not paraphrase** weather/report; only add minimal section headers for clarity.
