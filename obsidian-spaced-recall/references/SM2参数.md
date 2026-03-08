# SM-2（记忆曲线）参数与评分

本 skill 用 SM-2 的简化实现（与 Anki 思路一致）。每张卡维护：
- `ease`：熟练度（初始 2.5，下限 1.3）
- `interval_days`：间隔（天）
- `reps`：连续记住次数
- `due`：下次复习时间（Unix 时间戳，UTC 存储即可）

## 自评分（0-5）

用户只需给“感觉”：
- 5：秒答/很稳
- 4：答对但稍想
- 3：勉强答对/有点模糊
- 2：想了半天才对或差一点
- 1：基本不会
- 0：完全错/空白

脚本默认规则：
- `q < 3`：视为没记住（重置 reps，interval=1）
- `q >= 3`：正常增长 interval

## SM-2 更新公式（常用版本）

- ease 更新：
  - `ease = max(1.3, ease + (0.1 - (5-q)*(0.08 + (5-q)*0.02)))`
- interval 更新：
  - if `q < 3`:
    - `reps = 0`
    - `interval = 1`
  - else:
    - `reps += 1`
    - if `reps == 1`: `interval = 1`
    - elif `reps == 2`: `interval = 6`
    - else: `interval = round(interval * ease)`
- due：`due = now + interval_days * 86400`

说明：
- nightly 复习习惯更强时，可以把 due 对齐到“每天晚上的固定时刻”，但 MVP 先用时间戳即可。
