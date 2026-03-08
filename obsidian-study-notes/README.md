# obsidian-study-notes

把课堂录音、ASR 转写、讲义、错题、阶段复盘材料，整理成**适合长期积累与复习的 Obsidian Markdown 笔记**。

## 这个 skill 适合什么场景

- 用户发来课堂录音，想先转写再落库
- 用户发来 PDF / 讲义 / 图片，只想归档到资料区
- 用户发来错题，想按“一题一页”入库
- 用户想维护统一中文命名、统一 YAML、统一模板的高中学习笔记系统

## 目录说明

- `SKILL.md`：给 agent 的核心执行规则
- `assets/`：课堂笔记、错题、复盘、记忆卡片总表模板
- `references/`：记忆卡片、同步、索引维护、外部 AI 总结流程等说明
- `scripts/create_note.py`：批量/可重复生成笔记用的小脚本
- `scripts/sync_safe.sh`：安全执行 Obsidian Headless Sync 的脚本（已改成通过 `OBSIDIAN_VAULT_PATH` 配置）
- `system-prompts/学习Claw.systemPrompt.md`：对应学习 topic / 小 Claw 的脱敏版提示词

## 依赖

- Obsidian Vault
- `ob`（Obsidian Headless Sync CLI，如需自动同步）
- 如果要处理音频：还需要配合 `sensevoice-local`
- 如果要做记忆曲线：还需要配合 `obsidian-spaced-recall`

## 快速上手

### 1. 复制 skill

把整个目录复制到你的 OpenClaw skills 目录，例如：

```bash
cp -R obsidian-study-notes <WORKSPACE>/skills/
```

### 2. 配置 Vault 路径

同步脚本默认读取环境变量：

```bash
export OBSIDIAN_VAULT_PATH="/data/obsidian-vault"
```

### 3. 音频→转写→落库

如果输入是音频，先让 agent 按 `sensevoice-local` 做转写；转写结果出来后，再继续本 skill 的课堂笔记流程。

### 4. 课堂笔记/错题落库

- 资料类：只归档到 `资料/`
- 课堂类：归档原件，再生成/更新 `课堂笔记/`
- 错题类：按一题一页写到 `错题/`

## 示例

### 示例 1：课堂录音

用户说：

> 这是今天数学课录音，帮我整理到 Obsidian。

推荐流程：

1. 调 `sensevoice-local/scripts/transcribe_file.sh`
2. 把原音频归档到对应学科 `资料/`
3. 基于模板生成课堂笔记
4. 如有写入，再执行 `scripts/sync_safe.sh`

### 示例 2：错题图片

用户说：

> 这道地理错题帮我记一页。

推荐流程：

1. OCR / 理解题干
2. 在 `学习/B 学科/地理/错题/` 下新建一页
3. 按 `assets/错题模板（一题一页）.md` 填写
4. 需要时再自动生成非数学记忆卡片

### 示例 3：批量生成空白笔记壳

```bash
python3 scripts/create_note.py   --类型 课堂   --学科 数学   --日期 2026-03-05   --章节 "选择性必修二"   --主题 "导数的几何意义"   --来源 转写   --输出目录 ./demo-vault/学习/B\ 学科/数学/课堂笔记
```

## 对应小 Claw system prompt

已附在：`system-prompts/学习Claw.systemPrompt.md`

适合用法：

- 绑定到“学习”topic / thread / 专用 agent
- 强制它每次回复前先读 `skills/obsidian-study-notes/SKILL.md`
- 如果用户常发音频，再在 prompt 里保留对 `sensevoice-local` 的调用入口

## 注意事项

- 这套默认结构偏“高中学习系统”，如果你做大学/职业学习，建议重命名目录和模板字段
- 数学默认不自动生成记忆卡片；别的学科默认生成
- 本仓库是公开版副本，所以 README 里出现的路径都是示例或占位符，不是必须照抄
