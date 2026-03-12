# 服务器同步脚本（sync_safe）

用途：在服务器使用 Obsidian Headless Sync（`ob`）时，规避偶发的锁残留问题（"Another sync instance is already running"），并满足本流程的硬要求：**每次改动都做一次云同步**。

## 背景

Headless Sync 使用锁目录防止并发同步：
- 锁目录：`<库路径>/.obsidian/.sync.lock`

在某些情况下该目录会残留，导致后续 `ob sync` 误判。

## 硬规则（本 skill）

凡是对 Vault 有写入，就必须同步一次（优先用 `sync_safe.sh`）：
- 生成/更新：`复习/记忆卡片/*.md`
- 更新：`复习/.openclaw/间隔复习/sr.sqlite`
- 写入：`复习/.openclaw/间隔复习/pending.json`

## 推荐做法

每次同步前：
1) 若检测不到正在运行的 `ob sync` 进程 → 清理锁目录（存在则删除）
2) 执行 `ob sync`

## 脚本（本 skill 自带）

- `scripts/sync_safe.sh`

用法：
```bash
bash bash <WORKSPACE>/skills/obsidian-spaced-recall/scripts/sync_safe.sh
```

## 一次性配置（如未配置过）

```bash
ob login
ob sync-setup --vault <远端库ID> --path "<VAULT_PATH>" --device-name "<DEVICE_NAME>"
```
