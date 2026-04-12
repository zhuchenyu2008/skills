#!/usr/bin/env python3
"""Send a nicer HTML commute email via workspace/email/send_email.py.

This is a thin wrapper that builds a readable HTML card and sends both plain-text and HTML.

Usage:
  send_commute_email.py --to zhuchenyu2008@foxmail.com \
    --subject "出门提醒：10:05 最迟出发" \
    --title "出门提醒" \
    --subtitle "11:00 到 魅KTV·AI辅唱(鄞州天街店)" \
    --recommend "最迟 10:05 从家出发" \
    --details-json ./details.json

details-json schema (optional):
  {
    "options": [{"title":..., "totalMinutes":..., "breakdownText":...}, ...],
    "weather": "...",
    "links": [{"label":"导航", "url":"https://..."}, ...]
  }
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
from pathlib import Path


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def build_html_doc(title: str, subtitle: str, recommend: str, payload: dict | None) -> str:
    def parse_recommend(s: str) -> tuple[str, list[str]]:
        # Accept either newline-separated or '｜' separated strings.
        raw_lines = [x.strip() for x in s.replace("｜", "\n").split("\n") if x.strip()]
        if not raw_lines:
            return "", []
        primary = raw_lines[0]
        facts = raw_lines[1:]
        return primary, facts

    primary_line, fact_lines = parse_recommend(recommend)
    weather = (payload or {}).get("weather")
    chosen = (payload or {}).get("chosen")  # {title, key, breakdownText}
    # Note: user preference: email should not present multiple route options.
    options = []
    links = (payload or {}).get("links") or []

    def option_block(opt: dict) -> str:
        ot = esc(str(opt.get("title", "")))
        tm = opt.get("totalMinutes")
        tm_s = f"{tm} 分钟" if tm is not None else ""
        bd = esc(str(opt.get("breakdownText", "")))
        return (
            "<div class='opt'>"
            f"<div class='opt-title'>{ot}</div>"
            f"<div class='opt-meta'>预计 {esc(tm_s)}</div>"
            + (f"<div class='opt-bd'>{bd}</div>" if bd else "")
            + "</div>"
        )

    link_html = "".join(
        f"<a class='btn' href='{esc(l.get('url',''))}' target='_blank' rel='noopener'>{esc(l.get('label','链接'))}</a>"
        for l in links
        if l.get("url")
    )

    options_html = "".join(option_block(o) for o in options[:4])

    chosen_html = ""
    if chosen:
        ct = esc(str(chosen.get("title") or chosen.get("key") or ""))
        cbd = esc(str(chosen.get("breakdownText") or ""))
        chosen_html = (
            "<div class='row'><span class='k'>路线</span>"
            f"<span class='v'><b>{ct}</b>" + (f"<div style='margin-top:4px;color:#334;font-size:12px;white-space:pre-wrap'>{cbd}</div>" if cbd else "") + "</span></div>"
        )

    weather_html = (
        f"<div class='row'><span class='k'>天气</span><span class='v'>{esc(weather)}</span></div>"
        if weather
        else ""
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{esc(title)}</title>
<style>
  body {{ background:#f3f4f6; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif; margin:0; padding:16px; }}
  .card {{ max-width:640px; margin:0 auto; background:#fff; border:1px solid #e7e9f0; border-radius:14px; overflow:hidden; box-shadow:0 6px 22px rgba(15,23,42,0.06); }}
  .top {{ padding:16px 18px 8px 18px; color:#0b2a4a; }}
  .top .t {{ font-size:18px; font-weight:900; }}
  .top .s {{ margin-top:6px; font-size:13px; color:#334; opacity:0.9; }}
  .body {{ padding:10px 18px 16px 18px; }}
  .recommend {{ padding:14px 14px; border-radius:12px; background:#ffffff; border:1px solid #eef0f6; }}
  .recommend .k {{ font-size:12px; color:#667; opacity:0.9; }}
  .recommend .v {{ margin-top:6px; font-size:22px; font-weight:900; color:#0b2a4a; line-height:1.25; }}
  .facts {{ margin-top:10px; display:flex; flex-direction:column; gap:8px; }}
  .fact {{ display:block; box-sizing:border-box; width:100%; max-width:100%; padding:10px 12px; border-radius:10px; background:#f6f7fb; border:1px solid #eef0f6; color:#0b2a4a; font-size:13px; font-weight:800; overflow:hidden; }}
  .row {{ margin-top:12px; display:flex; gap:10px; font-size:13px; }}
  .row .k {{ width:64px; color:#667; }}
  .row .v {{ flex:1; color:#111; }}
  .btns {{ margin-top:14px; display:flex; flex-wrap:wrap; gap:10px; }}
  .btn {{ display:inline-block; padding:10px 12px; border-radius:10px; background:#111827; color:#fff !important; text-decoration:none; font-size:12px; }}
  .ftr {{ padding:12px 18px; font-size:11px; color:#667; border-top:1px solid #eef0f6; background:#fafbff; }}
  .muted {{ color:#667; font-size:12px; }}
</style>
</head>
<body>
  <div class='card'>
    <div class='top'>
      <div class='t'>{esc(title)}</div>
      <div class='s'>{esc(subtitle)}</div>
    </div>
    <div class='body'>
      <div class='recommend'>
        <div class='k'>出门提醒（主）</div>
        <div class='v'>{esc(primary_line)}</div>
        <div class='facts'>
          {''.join(["<div class='fact'>" + esc(x) + "</div>" for x in fact_lines])}
        </div>
      </div>
      {chosen_html}
      {weather_html}
      <div class='btns'>
        {link_html if link_html else ""}
      </div>
    </div>
    <div class='ftr'>
      由 OpenClaw 出行规划自动生成（高德MCP估时 + 你的习惯缓冲）。邮件以“出门提醒”为主；路线/天气仅作参考。若最迟出发时间变化≥5分钟会再次邮件提醒。
    </div>
  </div>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", required=True)
    ap.add_argument("--recommend", required=True)
    ap.add_argument("--details-json", default=None)
    args = ap.parse_args()

    payload = None
    if args.details_json:
        payload = json.loads(Path(args.details_json).read_text(encoding="utf-8"))

    html_body = build_html_doc(args.title, args.subtitle, args.recommend, payload)

    # Build a decent plain-text fallback
    lines = [
        f"{args.title}",
        args.subtitle,
        "",
        f"建议最迟出发：{args.recommend}",
    ]
    if payload and payload.get("chosen"):
        c = payload["chosen"]
        lines.append(f"路线：{c.get('title') or c.get('key')}")
        if c.get("breakdownText"):
            lines.append(f"  {c['breakdownText']}")
    if payload and payload.get("weather"):
        lines.append(f"天气：{payload['weather']}")
    if payload and payload.get("options"):
        lines.append("")
        lines.append("路线信息（次要）：")
        for o in payload["options"][:4]:
            lines.append(f"- {o.get('title','')}（约 {o.get('totalMinutes','?')} 分钟）")
            bd = o.get("breakdownText")
            if bd:
                lines.append(f"  {bd}")
    if payload and payload.get("links"):
        lines.append("")
        for l in payload["links"]:
            if l.get("url"):
                lines.append(f"{l.get('label','链接')}: {l['url']}")
    text_body = "\n".join(lines).strip() + "\n"

    sender = Path(__file__).resolve().parents[2] / "email" / "send_email.py"
    if not sender.exists():
        # fallback: workspace/email/send_email.py
        sender = Path(__file__).resolve().parents[3] / "email" / "send_email.py"

    cmd = [
        str(sender),
        "--to",
        args.to,
        "--subject",
        args.subject,
        "--text",
        text_body,
        "--html",
        html_body,
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(res.stderr.strip() or res.stdout.strip())


if __name__ == "__main__":
    main()
