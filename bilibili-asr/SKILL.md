---
name: bilibili-asr
description: Download Bilibili videos and transcribe them to Chinese text using local SenseVoice ASR. Use when the user sends Bilibili video URLs and asks to download, transcribe, or take notes from them. Handles 412 web-block by calling Bilibili API directly to get CDN download URLs.
---

# Bilibili ASR — 下载 B站视频并转写

## 核心能力

当用户发来 B站视频链接，要求"下载""转写""做笔记"时使用。

## 工作流

### Step 1 — 获取视频直链（绕412）

```python
import urllib.request, json

def get_bilibili_download_url(bvid: str, cid: int) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/'
    }
    url = f'https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=16&fnval=0&fnver=0&fourk=0'
    req = urllib.request.Request(url, headers=headers)
    d = json.load(urllib.request.urlopen(req))
    return d['data']['durl'][0]['url']
```

1. 从 `https://api.bilibili.com/x/player/pagelist?bvid=<BV号>` 获取 `cid`
2. 用上函数拿直链
3. 注意：直接访问 `bilibili.com` 网页会被 412，但 API 接口可以正常工作

### Step 2 — 下载视频

```bash
curl -L -o /tmp/${BV_ID}.mp4 "$VIDEO_URL" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  -H "Referer: https://www.bilibili.com/" \
  -H "Origin: https://www.bilibili.com/" \
  --max-filesize 500000000
```

- 默认下载到 `/tmp/`
- 注意：`--max-filesize` 防止下载超限视频时撑爆磁盘

### Step 3 — 转写（本地 SenseVoice）

使用 sensevoice-local skill 的批量转写脚本：

```bash
bash /root/.openclaw/workspace/skills/sensevoice-local/scripts/transcribe_batch_detached.sh \
  --batch-dir /tmp/bilibili_transcribe \
  /path/to/video1.mp4 \
  /path/to/video2.mp4
```

监控状态：

```bash
cat /tmp/bilibili_transcribe/state.json
```

等待 `status: success` 后读取转写结果：

- `/root/.openclaw/workspace/sensevoice-local/output/<文件名>.txt`

### Step 4 — 后续处理

- 转写文本 → 按 `obsidian-study-notes` skill 做课堂笔记
- 或直接交付转写文本

## 注意事项

- BV号格式：如 `BV1ts421u7Zb`，CID 为整数
- 视频版权/大会员内容：API 可能返回空，仍会失败
- 临时文件默认放 `/tmp/`，建议用完删除
- 本 skill 依赖 `sensevoice-local` skill 进行转写，需确保该 skill 已安装
