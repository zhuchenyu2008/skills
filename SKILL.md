---
name: amap-commute-planner
description: Plan Ningbo trips using AMap MCP with user defaults (home origin, metro-first with shared e-bike), produce multiple route options (fastest vs habitual vs direct e-bike), compute latest-departure-to-arrive-at-venue time (incl. inside-mall buffer), and schedule re-check reminders (10min cadence then 5min near departure) with Telegram+email alerts.
---

# AMap Commute Planner (Ningbo)

Use this skill when the user gives a time + destination and wants you to plan departure time and keep re-checking ETAs.

## Defaults (user-specific)
- **Authorization:** For this skill, the user (辰宇) has pre-authorized **read-only** checks by default (AMap POI search / routing / weather queries). No per-request permission is needed for these read-only lookups.
- **Auto-actions policy (explicit user preference):** 对于"出行规划/通勤"类的一句话请求,默认允许我直接完成:路线规划 + 时间计算 + **创建复算/提醒 cron(TG+邮件)**;不需要再问"要不要提醒/要不要复算"。
  - 仍然需要另外询问的情况:改 OpenClaw 配置/安装更新/重启服务/更换账号或收件人等超出本技能范围的变更。
- City default: 宁波 (unless user says otherwise)
- Origin default: home (金都嘉园52号, AMap lng,lat): `121.5230315924,29.8652491273`
- Common metro entry stations (choose among them for the "habit" plan):
  - 柳西(地铁站): `121.531320,29.871117`
  - 丽园南路(地铁站): `121.517716,29.858133`
  - 云霞路(地铁站): `121.526364,29.858542`
- Reminder threshold: if the *recommended departure time* changes by >= 5 minutes, notify; within ±2 minutes you may skip notifying.
- Recheck cadence: start at (T-30) every 10 min, then from (T-15) every 5 min, up to T.

## What to do for each request (user preference override)
**默认把用户的"一句话"当成完整指令:自动完成全流程**(不再额外确认):
1) POI 搜索/定位目的地
2) 路线规划(按默认规则选择并锁定路线;若用户明确说"直骑小遛",则锁定 bike_direct)
3) 计算"最迟出发时间"(含合理缓冲)
4) **将规划结果写入 state 文件**（格式见下）
5) **自动创建复算+提醒 cron**:按 T-30/-20/-15/-10/-5/0 的节奏复算;变动≥5分钟则 TG+邮件提醒;到点则 TG+邮件"立即出发"提醒

**State 文件格式（必须严格遵守，`cron_route_watch_decide.py` 依赖此格式）:**
```json
{
  "event": {
    "arriveByLocal": "{YYYY-MM-DD HH:MM}",
    "origin": "{lng,lat}",
    "destination": "{lng,lat}",
    "city": "宁波",
    "cityd": "宁波",
    "timezone": "Asia/Shanghai",
    "originName": "家",
    "name": "{目的地简称}"
  },
  "chosen": {
    "plan": "{planKey}"   // bike_direct / fastest / habit:柳西 等
  },
  "policy": {
    "buffer": {
      "insideVenueMinutes": {N},
      "waitAndFrictionMinutes": {N}
    },
    "notifyThresholdMinutes": 5
  },
  "notifications": {}
}
```

输出偏好:
- 默认对话里只给 **一条结论**(路程多久 + 最迟出发 + 到达时间/到点提醒已设定)。
- 只有用户明确要求"备选/限制条件(不骑车/只地铁等)"时才展开多方案。

## Route lock-in (required)
The route used for rechecks/reminders must be decided **at planning time**, not at departure time:
- Compute internally as needed, then **lock the fastest option** (overall fastest among available modes under current conditions).
- Store `chosenPlanKey` in state and **recheck the same plan** on each cadence.
- In every reminder, explicitly state: "本次提醒依据路线:...".
- Only switch route if the user asks, or if the chosen plan becomes invalid/unavailable.

For each option, output:
- Total ETA (minutes)
- A simple segment breakdown (e.g., bike-to-station + metro + walk + inside-mall)
- A **latest depart time** to arrive at the *venue* (not just the mall gate)

### Buffers (keep them realistic, not exaggerated)
Add buffers on top of AMap durations:
- `insideVenueMinutes` (default 10-15 for large malls; can be 0-5 for street-front POIs)
- `frictionMinutes` for metro/transfer/security/parking the e-bike (default 5-10; adapt by complexity)

### Weather-aware evaluation (required)
Before final recommendation, fetch weather for 宁波 (`amap.maps_weather` or the built-in `weather` skill) and adjust:
- Rain/strong wind/cold snap: down-rank **Direct 小遛**; prefer metro-based plans.
- Extreme heat: reduce walking-heavy plans.
- If user explicitly wants "时间最短",still show the fastest option even if weather is bad-just warn.

## How to get the destination
- If user sends place name: use AMap `maps_text_search` (citylimit=true) then `maps_search_detail` to get `location` and POI name/address.
- If user says "KTV in mall": prefer searching with a keyword including the venue (e.g., "龙湖天街 KTV") so you land on the specific shop POI.

## Route computation (tooling)
Use AMap MCP tools (via mcporter exec):
- `maps_direction_transit_integrated(origin, destination, city, cityd)`
- `maps_direction_bicycling(origin, destination)`
- `maps_direction_walking(origin, destination)`

Important limitation: the MCP planning tools do **not** take a departure-time parameter. Treat results as current/default ETA; use rechecks to adapt.

## Selecting metro-entry station for the Habit plan
For each candidate station:
1) Get bike ETA: origin → station (`maps_direction_bicycling`)
2) Get transit ETA: station → destination (`maps_direction_transit_integrated`)
3) Combine + buffers. Pick the best *among these stations*.

## Reminder scheduling
After you compute a chosen plan and latest depart time T:
- Create cron jobs at T-30, T-20, T-15, T-10, T-5, T (local time Asia/Shanghai).
- Each recheck job recomputes ETA for the chosen plan and updates T.
- If T shifts by >= 5 minutes: send Telegram + email.
- **到点出发提醒（T）**：send Telegram + email immediately.

### Critical implementation note
**Do NOT schedule these rechecks as `sessionTarget=main` + `payload.kind=systemEvent`.**
That pattern only injects a "System:" message into the chat log; it does **NOT** guarantee a proactive Telegram push.

**Correct pattern:** schedule as `sessionTarget="isolated"` + `payload.kind="agentTurn"` + **`delivery: {mode: "none"}`**.
This ensures the cron runs silently; only the agent decides when to push via the `message` tool.

In the agentTurn, call `scripts/cron_route_watch_decide.py` — this single script handles:
1. Running `recheck_trip.py` to recompute ETA
2. Determining whether to notify (`shouldNotify`/`departNow`)
3. Generating the complete email content (weather, route name, times) and sending it
4. Returning `pushTelegram` (bool) and `telegramText` for you to decide

**CRITICAL: Cron payload must contain explicit script commands, not just text descriptions.**

❌ 错误示例（Apr-04 incident）：
```
payload.message = "复查行程：目的地XXX，检查路况是否需要更新出发时间，如变动>=5分钟则发送TG+邮件提醒。"
```
这样写只会让 agent 回复文字，不会真正调用邮件脚本。

❌ 错误示例（手动拼邮件参数）：
```
# 不要自己拼 send_commute_email.py 的参数，内容会不完整
python3 scripts/send_commute_email.py --recommend "请立即出发｜..." --details-json ...
```

✅ 正确示例（出发提醒 T 和 复查提醒 T-X 统一用这个）：
```
python3 /root/.openclaw/workspace/skills/amap-commute-planner/scripts/cron_route_watch_decide.py \
  --state /root/.openclaw/workspace-travel/trip_state.json \
  --recipient-email zhuchenyu2008@foxmail.com
```
脚本输出 JSON，解析后：
- `pushTelegram`: `true` 时才用 `message` 工具发送 Telegram；`false` 时**保持静默，不发任何消息**
- `telegramText`：`pushTelegram=true` 时作为消息内容发送
- `email`：包含完整邮件内容（subject, title, subtitle, recommend, detailsJsonPath），**由脚本内部自动发送**
- `shouldEmail`：`true` 时邮件已自动发送（脚本内部处理）

```python
# 在 agentTurn 里示例
import json, subprocess
result = subprocess.run(
    ["python3", "/root/.openclaw/workspace/skills/amap-commute-planner/scripts/cron_route_watch_decide.py",
     "--state", "/root/.openclaw/workspace-travel/trip_state.json",
     "--recipient-email", "zhuchenyu2008@foxmail.com"],
    capture_output=True, text=True)
data = json.loads(result.stdout)
push_tg = data.get("pushTelegram", False)
telegram_text = data.get("telegramText", "")
# 邮件已由脚本内部发送，无需 agent 额外处理
if push_tg:
    # 用 message 工具发送 Telegram
    print("需要推送TG:" + telegram_text)
else:
    # 静默结束，不发任何消息
    pass
```

**判断逻辑：**
- `pushTelegram=true` → 出发时间到了，或时间变化 ≥5 分钟 → 用 `message` 工具发送 `telegramText` 到 TG
- `pushTelegram=false` → 时间无实质变化 → **不输出任何内容**，让 cron 静默结束

This ensures reminders actually reach the user with complete content (weather, route name, all time fields) — but only when they actually need to act.

### Notification policy (user preference)
- **Telegram + Email**
  - Email:以 **出门提醒** 为主;路线/天气为次要信息。
  - Telegram:同样会推送(避免漏看)。
- 触发规则(选 B):
  1) 到"最迟出发时间"T:发 Telegram + Email(出门提醒)
  2) 复查发现"最迟出发时间"变化 **>= 5 分钟**:发 Telegram + Email(更新提醒)

### Email
Enabled. Keep email layout/content fixed (confirmed):
- Header: **no blue/gradient banner**
- Title examples:
  - 到点:`出门提醒:请立即出发`
  - 更新:`出门提醒:最迟 HH:MM 出发`
- Main block (primary): action line + stacked facts (no parentheses):
  - `请立即出发` / `最迟 HH:MM`
  - `到达时间:HH:MM`
  - `路程约 XX 分钟`
- Secondary: route + weather
- No multi-route "options" section in email.

## Scripts
- `scripts/plan_trip.py` — 计算多条路线选项和最迟出发时间（供规划时调用）
- `scripts/recheck_trip.py` — 复查单个方案的 ETA 并更新 state（由 `cron_route_watch_decide.py` 内部调用）
- `scripts/cron_route_watch_decide.py` — **发邮件的标准入口**：复查 ETA + 判断是否通知 + 生成完整邮件内容并发送 + 返回 Telegram 文本
