# btc-position-watch

从交易 app 的**仓位截图**里提取参数，装一个按固定频率运行的邮件 watcher，用来盯当前仓位盈亏和 15 分钟方向。

## 适合什么场景

- 用户发来 Binance / OKX / Bybit 等仓位截图
- 用户明确说“帮我盯盘”“每 5 分钟发邮件”“盯着仓位”
- 你想用 cron 做一个稳定、可移除的 watcher

## 目录说明

- `SKILL.md`：agent 使用流程
- `references/screenshot_parsing.md`：截图参数提取建议
- `scripts/manage_cron_watch.py`：安装/移除 crontab block
- `scripts/position_mailer.py`：抓价格、算盈亏、发一封邮件

## 依赖

- Python 3
- root crontab 权限（安装 watcher 时）
- 你的邮件发送脚本：`email/send_email.py`
- 一个可访问的价格源（脚本内用 CryptoCompare，USD 回退 Coinbase）

## 先配工作区

脚本默认从环境变量读取：

```bash
export OPENCLAW_WORKSPACE="/opt/openclaw/workspace"
```

并假定邮件发送脚本在：

```text
$OPENCLAW_WORKSPACE/email/send_email.py
```

## 使用教程

### 1. 先从截图拿参数

最少需要：

- `symbol`
- `qty`
- `entry`
- `to`（收件邮箱）

### 2. 安装 watcher

```bash
sudo python3 scripts/manage_cron_watch.py install   --id btc1   --every-min 5   --to alerts@example.com   --symbol BTCUSDT   --qty -0.0042   --entry 67840   --tag "btc-short"
```

### 3. 立刻手动发一封测试邮件

```bash
python3 scripts/position_mailer.py   --to alerts@example.com   --symbol BTCUSDT   --qty -0.0042   --entry 67840   --tag "btc-short"
```

### 4. 停掉 watcher

```bash
sudo python3 scripts/manage_cron_watch.py remove --id btc1
```

## 示例

### 示例 1：用户说“这单帮我每 5 分钟发邮件盯着”

流程建议：

1. 先 OCR / 视觉读取截图
2. 如果仓位数量、方向或开仓价不清晰，最多问 1–2 个确认问题
3. 安装 cron block
4. 立即发送一封测试邮件
5. 把 watcher id 告诉用户，方便后续关闭

### 示例 2：用户说“停掉刚才那个盯盘”

- 如果你知道 id，直接 `remove --id <id>`
- 如果不知道 id，就先查 crontab 里 `BEGIN BTC_POSITION_WATCH` 标记块

## 对应小 Claw system prompt

这个 skill 通常**没有独立的小 Claw prompt**，更常见的是主 assistant 在识别到“截图 + 盯盘 + 邮件”时临时调用。

## 注意事项

- 这是仓位 watcher，不是完整交易机器人
- 默认邮件频率是 5 分钟；如果你想更频繁，先考虑 API 限频和邮件噪音
- 公开版已经去掉了私人邮箱和私有工作区路径
