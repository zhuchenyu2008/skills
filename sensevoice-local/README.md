# sensevoice-local

本地 SenseVoice ASR skill，用于把**中文课堂录音 / 大音频文件**转成文本；还带一个**一次性上传页**，方便在 Telegram 等渠道不方便传大文件时走网页上传。

## 适合什么场景

- 用户发来 mp3/m4a/wav 等课堂录音
- Bot 平台对音频大小有限制
- 你想在本机 CPU 上跑一个可控的 ASR fallback

## 目录说明

- `SKILL.md`：agent 使用规则
- `scripts/transcribe_file.sh`：转写包装脚本（通过 `SENSEVOICE_RUNTIME_DIR` 指向真正运行时）
- `scripts/upload_audio_once.sh`：一次性上传页启动脚本
- `scripts/serve_upload_once.py`：上传服务实现
- `references/upload-workflow.md`：上传 → 转写的详细流程
- `references/troubleshooting.md`：常见问题

## 依赖

- 已部署好的 SenseVoice 本地运行时
- Bash / Python 3
- 浏览器或聊天端用于打开上传链接

## 先配运行时路径

默认运行时目录是：

```bash
export SENSEVOICE_RUNTIME_DIR="/opt/sensevoice-local"
```

如果你想把上传文件放到固定目录：

```bash
export SENSEVOICE_UPLOAD_DIR="/data/uploads/sensevoice-local"
```

## 使用教程

### 1. 直接转写本地音频

```bash
bash scripts/transcribe_file.sh /path/to/audio.mp3
```

指定中文：

```bash
bash scripts/transcribe_file.sh --language zh /path/to/audio.mp3
```

### 2. 给用户开一次性上传页

```bash
bash scripts/upload_audio_once.sh   --port 18793   --state-file ./uploads/sensevoice-local/state.json
```

如果用户要从公网访问，推荐显式指定：

```bash
bash scripts/upload_audio_once.sh   --port 18793   --public-base http://your-public-host:18793   --state-file ./uploads/sensevoice-local/state.json
```

### 3. 上传成功后继续转写

读取 `state.json` 里最终的 `path`，然后：

```bash
bash scripts/transcribe_file.sh /path/to/uploaded-audio.mp3
```

## 示例

### 示例 1：学习 topic 里有人说“我要上传大音频”

1. 小 Claw 先调用 `upload_audio_once.sh`
2. 把 `upload_url` 发给用户
3. 用户上传 1 个文件后，页面自动关闭
4. 读取返回路径，接着跑 `transcribe_file.sh`
5. 再把转写结果喂给 `obsidian-study-notes`

### 示例 2：本地测试上传页

```bash
python3 scripts/serve_upload_once.py --listen 127.0.0.1 --port 18793 --output-dir ./tmp-upload
```

## 对应小 Claw system prompt

这个 skill **通常没有独立的小 Claw 提示词**，而是被 `obsidian-study-notes` 或别的学习流程调用。

如果你要接入学习 agent，最简单的做法是在学习 prompt 里加一条硬规则：

- 遇到音频先走 `sensevoice-local`
- 遇到“上传大文件/开上传页”先走一次性上传流程

## 注意事项

- 这是本地 fallback，不是云端最强识别
- 长音频建议先保证上传链路和磁盘空间稳定
- 上传页默认就是单次使用，不要长期暴露
