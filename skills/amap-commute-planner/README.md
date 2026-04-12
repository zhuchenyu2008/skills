# Public OpenClaw Skills (sanitized export)

这是一个**脱敏后的 skill 源码仓库**，整理自我当前在 OpenClaw 工作区里实际使用过的一组技能。这里放的是**可公开分享的副本**：保留了核心流程、脚本和说明，同时去掉了私人邮箱、固定公网 IP、私有路径、群组绑定等环境细节。

## 收录技能

| Skill | 作用 | 是否附带对应小 Claw system prompt |
|---|---|---|
| [obsidian-study-notes](./obsidian-study-notes/) | 把课堂录音/转写/资料/错题落库成结构化 Obsidian 学习笔记 | 是 |
| [obsidian-spaced-recall](./obsidian-spaced-recall/) | 基于 SM-2 做记忆卡片抽查、逐题复习和调度 | 是 |
| [sensevoice-local](./sensevoice-local/) | 本地 SenseVoice ASR + 一次性上传页，用于大音频转写 | 否（通常由学习流程调用） |
| [morning-brief](./morning-brief/) | 聚合天气 + RSS-AI 日报，生成 Telegram 语音早报 | 是 |
| [btc-position-watch](./btc-position-watch/) | 从仓位截图参数出发，安装/移除邮件盯盘 cron watcher | 否 |

## 这份仓库做了哪些脱敏

- 把私人邮箱改成占位符（如 `<ALERT_EMAIL>`）
- 把固定公网 IP / host 改成占位符（如 `<PUBLIC_IP_OR_HOST>` / `<PUBLIC_HOST>`）
- 把私有工作区 / vault 路径改成占位符或环境变量（如 `<WORKSPACE>`、`<VAULT_PATH>`）
- 把 Telegram 群组 / topic 绑定信息从 prompt 中抽离为通用写法
- 把个性化称呼、固定地点等改成可配置字段

## 占位符约定

- `<WORKSPACE>`：你的 OpenClaw 工作区根目录
- `<VAULT_PATH>`：你的 Obsidian Vault 路径
- `<SYNC_SAFE_SCRIPT>`：你放置同步脚本的位置
- `<ALERT_EMAIL>`：接收提醒邮件的邮箱
- `<PUBLIC_HOST>` / `<PUBLIC_IP_OR_HOST>`：用户可访问上传页的公网地址
- `<USER_NAME>`：你的用户昵称（如需要个性化称呼）

## 使用方式

1. 选一个 skill 目录，复制到你的 OpenClaw skills 目录。  
2. 按该 skill README 把占位符换成你自己的配置。  
3. 先跑 README 里的最小示例，确认脚本能工作。  
4. 如果你有对应 topic-agent / 小 Claw，再参考该 skill 内的 `system-prompts/` 文件接入。  

## 推荐阅读顺序

- 想做学习落库：先看 `obsidian-study-notes/README.md`
- 想做 nightly 抽查：再看 `obsidian-spaced-recall/README.md`
- 想处理大录音：补看 `sensevoice-local/README.md`
- 想做定时语音早报：看 `morning-brief/README.md`
- 想做截图盯盘：看 `btc-position-watch/README.md`

## 提醒

这些 skill 来自真实私用环境，所以 README 里会明确写依赖和边界；如果你要直接拿去公开发布，建议再按自己的环境做一次二次清理。
