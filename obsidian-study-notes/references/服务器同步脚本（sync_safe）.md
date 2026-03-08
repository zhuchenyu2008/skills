# 服务器同步脚本（sync_safe）

用途：在服务器使用 Obsidian Headless Sync（`ob`）时，规避偶发的锁残留问题（"Another sync instance is already running"）。

## 背景

Headless Sync 使用锁目录防止并发同步：
- 锁目录：`<库路径>/.obsidian/.sync.lock`

在某些情况下该目录会残留，导致后续 `ob sync` 误判。

## 推荐做法

每次同步前：
1) 若检测不到正在运行的 `ob sync` 进程 → 清理锁目录（存在则删除）
2) 执行 `ob sync`

## 脚本（服务器）

Skill 自带脚本：`scripts/sync_safe.sh`

## 安装方式（示例）

将脚本复制到常用位置并修改库路径：

```bash
cp /path/to/skill/obsidian-study-notes/scripts/sync_safe.sh <SYNC_SAFE_SCRIPT>
chmod +x <SYNC_SAFE_SCRIPT>
# 编辑脚本内 VAULT_PATH 为你的本地库路径
```

## 用法

```bash
<SYNC_SAFE_SCRIPT>
```

## 一次性配置

```bash
ob login
ob sync-setup --vault <远端库ID> --path "<VAULT_PATH>" --device-name "<DEVICE_NAME>"
```
