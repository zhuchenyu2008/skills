# obsidian-spaced-recall

基于 **SM-2** 的 Obsidian 记忆卡片抽查与复习调度 skill。它负责把卡片扫入题库、挑出到期卡片、维护 pending/hold/commit 流程，并把复习状态回写到卡片文件里；也支持凌晨生成“今日复习笔记”和聊天侧的语义召回辅助讲题。

## 适合什么场景

- 你已经有一套学习笔记，希望把“老师会考的点”做成独立卡片
- 你想做 nightly 定时抽查
- 你想在聊天里逐题复习，而不是一次刷一堆题
- 你想把“复习记录 + 下次复习时间”写回 Obsidian

## 目录说明

- `SKILL.md`：agent 用的复习流程规则
- `scripts/sr_cli.py`：扫描、出题、hold、commit、status 等核心脚本
- 配合外部定时脚本时，也可在凌晨生成“今日复习笔记”，把所有到期题及相关旧材料先整理出来
- `scripts/sync_safe.sh`：写入后同步 vault 的脚本
- `references/`：卡片格式、SM-2 参数、与学习笔记系统联动说明
- `system-prompts/每日复习Claw.systemPrompt.md`：对应每日复习小 Claw 的脱敏版提示词

## 依赖

- Python 3.10+
- Obsidian Vault
- `ob`（如果你要每次写入后自动同步）
- 最好和 `obsidian-study-notes` 配套使用

## 快速上手

### 1. 扫描卡片入库

```bash
python3 scripts/sr_cli.py scan --vault /data/obsidian-vault
```

### 2. 查看题库状态

```bash
python3 scripts/sr_cli.py status --vault /data/obsidian-vault
```

### 3. 抽取当前到期题

```bash
python3 scripts/sr_cli.py next --vault /data/obsidian-vault --all-due
```

### 4. 用户答题后先 hold

```bash
python3 scripts/sr_cli.py hold --vault /data/obsidian-vault --q 3 --answer "用户原话"
```

### 5. 确认后 commit

```bash
python3 scripts/sr_cli.py commit --vault /data/obsidian-vault
```

## 示例流程

### 示例 1：nightly 复习

1. cron / agent 定时触发 `scan`
2. 若 `due_now > 0`，先报题量拆分：当前已到期 = 积压 + 今日新增
3. 再执行 `next --all-due`
4. 小 Claw 在聊天里只发 1 题
5. 用户作答后，先判对错，再 `hold`
6. 答对可直接 `commit`；答错则讲清楚后等“下一题/继续”再 `commit`

### 示例 2：用户手动说“复习”

- 先 `scan`
- 再 `status`
- 如果没有到期卡片，就告诉用户今天可休息
- 如果有未完成 pending，就提示“继续/下一题”或“停止复习”

## 对应小 Claw system prompt

已附在：`system-prompts/每日复习Claw.systemPrompt.md`

建议把这个 prompt 绑定到一个单独 topic / thread，让它只做：

- 出题
- 判分
- hold / commit
- 同步

不要让它顺手去做资料整理，否则体验会混乱。

## 注意事项

- `sr_cli.py` 默认把状态放在 `复习/.openclaw/间隔复习/`
- 卡片建议尽量小：一张卡只考一个点
- 若写入了卡片或状态，记得同步 Vault
