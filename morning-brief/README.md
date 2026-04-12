# morning-brief

把**多模型天气共识 + RSS-AI 日报**整理成中文口播稿，做成本地 TTS 语音，然后发到 Telegram topic / forum thread 的早报 skill。

## 适合什么场景

- 你想每天固定时间自动发一条中文语音早报
- 你已经有 Telegram Bot、TTS 服务和 RSS-AI 数据源
- 你希望天气不是单一来源，而是多模型交叉比对后的结论

## 目录说明

- `SKILL.md`：agent 使用说明
- `scripts/morning_brief.py`：主脚本
- `examples/config.example.json`：脱敏后的配置示例
- `system-prompts/早报Claw.systemPrompt.md`：对应早报小 Claw 的脱敏版提示词

## 依赖

- Python 3
- `ffmpeg`
- 一个兼容的本地 TTS HTTP 服务（如 piper-http）
- Telegram Bot Token
- 一个 RSS-AI 报告接口
- OpenClaw CLI（脚本内部会调用 `openclaw agent` 生成问候和口播稿）

## 配置

先参考：`examples/config.example.json`

重点字段：

- `telegram.bot_token`：Telegram Bot Token
- `telegram.chat_id`：群或频道 ID
- `telegram.message_thread_id`：topic / 线程 ID
- `sources.rssai_base_url`：日报来源
- `tts.base_url`：TTS 服务地址
- `location`：天气地理位置
- `assistant.user_name`：如需个性化称呼，可填用户名字；不填也能工作
- `assistant.workspace_dir`：如果你想让脚本参考 OpenClaw memory 自动生成早安问候，可填写；不填则只生成通用问候
- `assistant.greeting_session_id` / `assistant.brief_session_id`：可选，自定义两个 OpenClaw agent 会话 ID，方便把“问候”和“口播稿”上下文分开
- `weather.request_retries` / `weather.request_backoff_seconds` / `weather.retry_failed_serially`：Open-Meteo 抓取抖动时的重试与串行补抓参数
- `limits.weather_prompt_max_chars` / `limits.rss_prompt_max_chars`：给 agent 的天气 JSON / 日报原文安全裁剪上限，避免 prompt 过长

## 使用教程

### 1. 先 dry run

```bash
python3 scripts/morning_brief.py --config examples/config.example.json --dry-run
```

这一步主要检查：

- 天气抓取是否成功（脚本会把成功/失败来源写到 stderr）
- RSS-AI 来源是否可用
- 生成的口播稿是否符合你的风格

### 2. 正式发送

```bash
python3 scripts/morning_brief.py --config /path/to/your/config.json
```

### 3. 挂到 cron

```cron
CRON_TZ=Asia/Shanghai
0 5 * * * cd /path/to/morning-brief && /usr/bin/python3 scripts/morning_brief.py --config /path/to/config.json
```

## 示例

### 示例 1：每天 05:00 发群 topic 早报

- Telegram 目标：固定群 topic
- 内容：天气共识 + 最新 RSS-AI 日报
- 形式：先发一条短问候，再发语音

### 示例 2：只测试文案，不发 Telegram

```bash
python3 scripts/morning_brief.py --config /path/to/config.json --dry-run > brief.txt
```

## 对应小 Claw system prompt

已附在：`system-prompts/早报Claw.systemPrompt.md`

建议把它绑定到专门的“早报”agent / topic，并保持边界单一：

- 只负责生成/发送早报
- 闲聊尽量短
- 真正发报时走脚本，不靠手写

## 注意事项

- 这份公开版已经把私有地名、私人称呼、工作区路径改成可配置项
- 如果你不想让脚本读取 memory，直接不填 `assistant.workspace_dir` 即可
- 发送前最好先 dry run 一次，避免 TTS 或 Telegram 参数填错
- 脚本内置了天气接口瞬时错误重试、失败模型串行补抓，以及 prompt 安全裁剪；如果你接自己的数据源，建议保留这些保护
