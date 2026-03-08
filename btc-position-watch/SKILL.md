---
name: btc-position-watch
description: Monitor a crypto (especially BTC) position when the user sends a trading-app position screenshot and asks you to “盯着仓位/帮我盯盘/每5分钟发邮件”. Extract symbol/qty/entry from the screenshot, then set up or stop a repeating email watcher (usually every 5 minutes) using a root crontab job that runs a bundled mailer script.
---

# BTC Position Watch（仓位截图 → 定时邮件盯盘）

Use this workflow when the user posts a **仓位截图** and explicitly asks you to **watch/monitor** and **send periodic emails** (default: every 5 minutes).

## Workflow

### 1) Parse the screenshot → get watch parameters

1. Use vision/OCR to extract (minimum required):
   - `symbol` (default: `BTC-USD`)
   - `qty` (positive=做多/long, negative=做空/short)
   - `entry` (开仓均价/入场价)
2. If ambiguous, ask at most 1–2 confirmation questions.
3. If user only wants “盯着”，but **did not say email**, confirm delivery channel (Telegram vs email).

Reference: `references/screenshot_parsing.md`.

### 2) Confirm delivery + cadence

- Recipient email (`--to`): confirm it explicitly (or use the user’s specified email).
- Cadence: default `every 5 min` unless user requests otherwise.
- Optional: add a short `tag` (e.g. `btc-short`) so the email subject is searchable.

### 3) Install the watcher (root crontab)

Use the bundled installer to create a deterministic cron block:

```bash
sudo python3 skills/btc-position-watch/scripts/manage_cron_watch.py install \
  --id btc1 --every-min 5 \
  --to <EMAIL> --symbol BTC-USD --qty <QTY> --entry <ENTRY> \
  --tag "btc" \
  --note "from screenshot @ <time>"
```

- Logs go to: `<WORKSPACE>/watchers/logs/btc_position_watch_<id>.log`
- Uses `flock` to prevent overlapping runs.

Immediately after installing, run one manual send to validate:

```bash
python3 skills/btc-position-watch/scripts/position_mailer.py \
  --to <EMAIL> --symbol BTC-USD --qty <QTY> --entry <ENTRY> --tag "btc"
```

### 4) Stop / remove the watcher

If the user says “关掉/停掉/别发了/结束盯盘”，remove by id:

```bash
sudo python3 skills/btc-position-watch/scripts/manage_cron_watch.py remove --id btc1
```

If id is unknown, inspect root crontab and look for `BEGIN BTC_POSITION_WATCH` blocks.

## Bundled scripts

- `scripts/position_mailer.py`: fetch spot price (Coinbase; fallback CryptoCompare), compute PnL from `qty/entry`, and send one email via workspace `email/send_email.py`.
- `scripts/manage_cron_watch.py`: install/remove the cron block (BEGIN/END markers).
