#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create Obsidian notes with Chinese naming and YAML frontmatter.

This script is optional; use when deterministic batch creation is needed.

Examples:
  python3 create_note.py --类型 课堂 --学科 数学 --日期 2026-03-05 --章节 "选择性必修二" --主题 "导数的几何意义" --来源 转写 --输出目录 ./vault/01 学科/数学/课堂笔记

  python3 create_note.py --类型 错题 --学科 数学 --日期 2026-03-05 --章节 "圆锥曲线" --知识点 "离心率" --来源 "练习册第32页第8题" --错因标签 "审题偏差,公式不熟" --输出目录 ./vault/01 学科/数学/错题/圆锥曲线
"""

import argparse
import os
from datetime import datetime

TEMPLATES = {
    "课堂": "assets/课堂笔记模板.md",
    "错题": "assets/错题模板（一题一页）.md",
    "复盘": "assets/复盘模板.md",
}


def safe_filename(name: str) -> str:
    # Prefer Chinese-only filenames; avoid path separators and problematic whitespace.
    return (
        name.replace("/", "－")
        .replace("\\", "－")
        .replace("\n", " ")
        .replace("\t", " ")
        .strip()
    )


def render(tpl: str, data: dict) -> str:
    out = tpl
    for k, v in data.items():
        out = out.replace("{{" + k + "}}", str(v or ""))
    return out


def find_template_path(skill_dir: str, rel: str) -> str:
    return os.path.join(skill_dir, rel)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_unique(path: str, content: str) -> str:
    base, ext = os.path.splitext(path)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    i = 2
    while True:
        candidate = f"{base}（{i}）{ext}"
        if not os.path.exists(candidate):
            with open(candidate, "w", encoding="utf-8") as f:
                f.write(content)
            return candidate
        i += 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--类型", required=True, choices=list(TEMPLATES.keys()))
    p.add_argument("--学科", required=True)
    p.add_argument("--日期", required=True)  # YYYY-MM-DD
    p.add_argument("--章节", default="")

    p.add_argument("--主题", default="")
    p.add_argument("--知识点", default="")
    p.add_argument("--来源", default="")
    p.add_argument("--错因标签", default="")  # 逗号分隔，如：审题偏差,公式不熟

    p.add_argument("--输出目录", required=True)
    args = p.parse_args()

    # validate date
    datetime.strptime(args.日期, "%Y-%m-%d")

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl_path = find_template_path(skill_dir, TEMPLATES[args.类型])
    tpl = read_text(tpl_path)

    def parse_tags(s: str):
        if not s:
            return []
        # allow comma/Chinese comma separated input
        parts = []
        for raw in s.replace("，", ",").split(","):
            t = raw.strip()
            if t:
                parts.append(t)
        return parts

    def yaml_inline_list(items):
        # conservative quoting
        def q(x: str) -> str:
            return '"' + x.replace('\\', '\\\\').replace('"', '\\"') + '"'
        return "[" + ", ".join(q(i) for i in items) + "]"

    tags = parse_tags(args.错因标签)

    data = {
        "学科": args.学科,
        "日期": args.日期,
        "章节": args.章节,
        "主题": args.主题,
        "知识点": args.知识点,
        "来源": args.来源,
        # template expects a YAML list literal
        "错因标签": yaml_inline_list(tags),
    }

    content = render(tpl, data)

    if args.类型 == "课堂":
        title_bits = [args.日期, args.学科, "课堂"]
        if args.章节 or args.主题:
            title_bits.append((args.章节 + " " + args.主题).strip())
        else:
            title_bits.append("本节课主题待定")
    elif args.类型 == "错题":
        title_bits = [args.日期, args.学科, "错题"]
        title_bits.append(args.知识点 or "知识点待定")
        title_bits.append(args.来源 or "来源待补")
    else:
        title_bits = [args.日期, args.学科, "复盘", args.主题 or "主题待定"]

    filename = safe_filename(" ".join([b for b in title_bits if b])) + ".md"
    os.makedirs(args.输出目录, exist_ok=True)
    out_path = os.path.join(args.输出目录, filename)

    final_path = write_unique(out_path, content)
    print(final_path)


if __name__ == "__main__":
    main()
