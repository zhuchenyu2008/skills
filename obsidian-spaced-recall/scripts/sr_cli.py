#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Obsidian spaced-recall helper (MVP).

Subcommands:
- scan:   scan vault markdown notes for '## 记忆卡片' and index cards
- quiz:   select due cards and create a pending quiz
- grade:  parse user self-ratings (0-5) and update SM-2 schedule
- status: show counts

Design goals:
- stdlib only
- store state inside vault: 学习/.openclaw/间隔复习/
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


# In card files under 复习/记忆卡片/, use a dedicated section heading.
CARD_HEADING_RE = re.compile(r"^#{1,6}\s*(卡片|记忆卡片|记忆卡)\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s+")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
QA_RE = re.compile(r"^(?P<q>.+?)\s*::\s*(?P<a>.+?)\s*$")
CLOZE_RE = re.compile(r"\{\{c1::(.*?)(?:::.*?)?\}\}")
RATING_PAIR_RE = re.compile(r"(?P<n>\d+)\s*[:=\s]\s*(?P<q>[0-5])")
AUTO_STATUS_BEGIN = "<!-- SR_STATUS:BEGIN -->"
AUTO_STATUS_END = "<!-- SR_STATUS:END -->"
AUTO_STATUS_BLOCK_RE = re.compile(r"\n*<!-- SR_STATUS:BEGIN -->.*?<!-- SR_STATUS:END -->\n*", re.S)
DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


@dataclasses.dataclass
class Card:
    card_id: str
    file_path: str  # path relative to vault root
    line_no: int
    kind: str  # qa|cloze
    prompt: str
    answer: str
    raw: str


def eprint(*args):
    print(*args, file=sys.stderr)


def now_ts() -> int:
    return int(time.time())


def vault_path_from_args(args) -> Path:
    vp = args.vault or os.environ.get("OBSIDIAN_VAULT") or os.environ.get("VAULT_PATH")
    if not vp:
        raise SystemExit("Missing --vault (or env OBSIDIAN_VAULT)")
    p = Path(vp).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"Vault not found: {p}")
    return p


def state_dir(vault: Path) -> Path:
    # Keep SR state inside the vault, but separate from study notes.
    p = vault / "复习" / ".openclaw" / "间隔复习"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path(vault: Path) -> Path:
    return state_dir(vault) / "sr.sqlite"


def pending_path(vault: Path) -> Path:
    return state_dir(vault) / "pending.json"


def hold_path(vault: Path) -> Path:
    return state_dir(vault) / "hold.json"


def fmt_ts_local(ts: Optional[int]) -> str:
    if ts in (None, 0, ""):
        return "未复习"
    return datetime.fromtimestamp(int(ts), tz=DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")


def callout_kind_for(last_q: Optional[int]) -> str:
    if last_q is None:
        return "info"
    q = int(last_q)
    if q >= 4:
        return "tip"
    if q <= 2:
        return "warning"
    return "info"


def score_label(last_q: Optional[int]) -> str:
    return str(last_q) if last_q is not None else "未复习"


def ease_label(ease: Optional[float]) -> str:
    return f"{float(ease):.2f}" if ease is not None else "未复习"


def file_paths_for_card_ids(con: sqlite3.Connection, card_ids: List[str]) -> List[str]:
    if not card_ids:
        return []
    placeholders = ",".join("?" for _ in card_ids)
    rows = con.execute(
        f"SELECT DISTINCT file_path FROM cards WHERE card_id IN ({placeholders}) ORDER BY file_path ASC",
        card_ids,
    ).fetchall()
    return [str(r[0]) for r in rows]


def refresh_status_sections(con: sqlite3.Connection, vault: Path, file_paths: Optional[List[str]] = None) -> int:
    sql = (
        "SELECT c.file_path, c.line_no, c.prompt, s.last_q, s.ease, s.last_review_ts, s.due_ts "
        "FROM cards c JOIN schedule s ON s.card_id=c.card_id"
    )
    params: List[object] = []
    if file_paths:
        placeholders = ",".join("?" for _ in file_paths)
        sql += f" WHERE c.file_path IN ({placeholders})"
        params.extend(file_paths)
    sql += " ORDER BY c.file_path ASC, c.line_no ASC, c.prompt ASC"

    rows = con.execute(sql, params).fetchall()
    by_file: Dict[str, List[Tuple[int, str, Optional[int], Optional[float], Optional[int], Optional[int]]]] = {}
    if file_paths:
        by_file.update({str(fp): [] for fp in file_paths})
    for file_path, line_no, prompt, last_q, ease, last_review_ts, due_ts in rows:
        by_file.setdefault(str(file_path), []).append(
            (
                int(line_no),
                str(prompt),
                None if last_q is None else int(last_q),
                None if ease is None else float(ease),
                last_review_ts,
                due_ts,
            )
        )

    updated_files = 0
    for rel_path, items in by_file.items():
        md = vault / rel_path
        if not md.exists():
            continue

        try:
            text = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = md.read_text(encoding="utf-8", errors="ignore")

        base = AUTO_STATUS_BLOCK_RE.sub("\n", text).rstrip()
        if not items:
            new_text = (base + "\n") if base else ""
        else:
            lines = [AUTO_STATUS_BEGIN, "## 复习状态（自动生成）", "", "> 这一段由记忆曲线脚本自动回写，别手改。", ""]
            for idx, (_line_no, prompt, last_q, ease, last_review_ts, due_ts) in enumerate(items):
                lines.append(f"> [!{callout_kind_for(last_q)}] {prompt}")
                lines.append(f"> 上次评分：{score_label(last_q)}")
                lines.append(f"> 熟练度：{ease_label(ease)}")
                lines.append(f"> 上次复习：{fmt_ts_local(last_review_ts)}")
                lines.append(f"> 下次复习：{fmt_ts_local(due_ts) if due_ts is not None else '未安排'}")
                if idx != len(items) - 1:
                    lines.append("")
            lines.append(AUTO_STATUS_END)
            block = "\n".join(lines)
            new_text = f"{base}\n\n{block}\n" if base else f"{block}\n"

        if new_text != text:
            md.write_text(new_text, encoding="utf-8")
            updated_files += 1

    return updated_files


def connect_db(vault: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path(vault)))
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
          card_id TEXT PRIMARY KEY,
          file_path TEXT NOT NULL,
          line_no INTEGER NOT NULL,
          kind TEXT NOT NULL,
          prompt TEXT NOT NULL,
          answer TEXT NOT NULL,
          raw TEXT NOT NULL,
          updated_at INTEGER NOT NULL
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule (
          card_id TEXT PRIMARY KEY,
          ease REAL NOT NULL,
          interval_days INTEGER NOT NULL,
          reps INTEGER NOT NULL,
          due_ts INTEGER NOT NULL,
          last_review_ts INTEGER,
          last_q INTEGER,
          lapses INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(card_id) REFERENCES cards(card_id) ON DELETE CASCADE
        );
        """
    )

    cols = {row[1] for row in con.execute("PRAGMA table_info(schedule)")}
    if "last_q" not in cols:
        con.execute("ALTER TABLE schedule ADD COLUMN last_q INTEGER")

    con.commit()
    return con


def parse_frontmatter_status(lines: List[str]) -> Optional[str]:
    if not lines or lines[0].strip() != "---":
        return None
    # naive YAML frontmatter parser: only care about 状态:
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            break
        m = re.match(r"^状态\s*:\s*(.+?)\s*$", lines[i])
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def iter_markdown_files(vault: Path) -> Iterable[Path]:
    # Only scan card files under 复习/记忆卡片 by default.
    root = vault / "复习" / "记忆卡片"
    if not root.exists():
        # backward-compatible fallback
        root = vault / "学习"
        if not root.exists():
            root = vault

    for p in root.rglob("*.md"):
        parts = set(p.parts)
        if ".obsidian" in parts:
            continue
        if ".openclaw" in parts:
            continue
        yield p


def normalize_rel_path(vault: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(vault.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def card_id_for(rel_path: str, raw_line: str) -> str:
    h = hashlib.sha1()
    h.update(rel_path.encode("utf-8"))
    h.update(b"|")
    h.update(raw_line.strip().encode("utf-8"))
    return h.hexdigest()


def normalize_dedupe_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = (
        text.replace("；", ";")
        .replace("，", ",")
        .replace("。", ".")
        .replace("：", ":")
        .replace("（", "(")
        .replace("）", ")")
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )
    text = re.sub(r"[\s_\-–—]+", "", text)
    text = re.sub(r"[\"'`·•]+", "", text)
    text = re.sub(r"[.,;:!?，。；：！？、/\\]+", "", text)
    return text


def dedupe_key_for_card(card: Card) -> Tuple[str, str, str]:
    return (card.kind, normalize_dedupe_text(card.prompt), normalize_dedupe_text(card.answer))


def dedupe_cards(con: sqlite3.Connection, cards: List[Card]) -> Tuple[List[Card], List[Dict[str, object]]]:
    if not cards:
        return [], []

    ids = [c.card_id for c in cards]
    placeholders = ",".join("?" for _ in ids)
    rows = con.execute(
        f"SELECT card_id, reps, interval_days, due_ts, last_review_ts, last_q FROM schedule WHERE card_id IN ({placeholders})",
        ids,
    ).fetchall()
    snapshots = {
        str(card_id): {
            "reps": int(reps),
            "interval_days": int(interval_days),
            "due_ts": int(due_ts),
            "last_review_ts": None if last_review_ts is None else int(last_review_ts),
            "last_q": None if last_q is None else int(last_q),
        }
        for card_id, reps, interval_days, due_ts, last_review_ts, last_q in rows
    }

    grouped: Dict[Tuple[str, str, str], List[Card]] = {}
    for card in cards:
        grouped.setdefault(dedupe_key_for_card(card), []).append(card)

    kept: List[Card] = []
    dropped: List[Dict[str, object]] = []

    for key, group in grouped.items():
        if len(group) == 1:
            kept.append(group[0])
            continue

        def score(card: Card):
            snap = snapshots.get(card.card_id)
            if snap is None:
                return (0, -1, -1, -1, -1)
            return (
                1,
                int(snap["reps"]),
                -int(snap["interval_days"]),
                -int(snap["last_review_ts"] or 0),
                int(snap["last_q"] if snap["last_q"] is not None else -1),
            )

        preferred = sorted(group, key=lambda c: (-score(c)[0], -score(c)[1], -score(c)[4], score(c)[2], score(c)[3], c.file_path, c.line_no, c.card_id))[0]
        kept.append(preferred)
        for card in group:
            if card.card_id == preferred.card_id:
                continue
            dropped.append({
                "dropped_card_id": card.card_id,
                "kept_card_id": preferred.card_id,
                "prompt": card.prompt,
                "answer": card.answer,
                "dropped_file": card.file_path,
                "dropped_line": card.line_no,
                "kept_file": preferred.file_path,
                "kept_line": preferred.line_no,
                "reason": "normalized prompt+answer duplicate",
                "dedupe_key": key,
            })

    kept.sort(key=lambda c: (c.file_path, c.line_no, c.card_id))
    return kept, dropped


def prune_cards_for_scanned_files(con: sqlite3.Connection, scanned_files: List[str], keep_card_ids: List[str]) -> int:
    if not scanned_files:
        return 0
    keep = set(keep_card_ids)
    to_delete: List[str] = []
    for rel_path in scanned_files:
        rows = con.execute("SELECT card_id FROM cards WHERE file_path=?", (rel_path,)).fetchall()
        for (card_id,) in rows:
            if str(card_id) not in keep:
                to_delete.append(str(card_id))
    if not to_delete:
        return 0
    con.executemany("DELETE FROM cards WHERE card_id=?", [(cid,) for cid in to_delete])
    con.commit()
    return len(to_delete)


def extract_cards_from_lines(rel_path: str, lines: List[str]) -> List[Card]:
    """Extract cards from a card file.

    Preferred format:
    - A section heading: '## 卡片' (or '## 记忆卡片')
    - List items under that heading containing either '问题::答案' or '{{c1::...}}'

    If no heading is found, fall back to scanning list items in the whole file.
    """

    cards: List[Card] = []

    def parse_item(item: str, line_no: int):
        item = item.strip()
        if not item:
            return

        m = QA_RE.match(item)
        if m:
            q = m.group("q").strip()
            a = m.group("a").strip()
            cid = card_id_for(rel_path, item)
            cards.append(Card(cid, rel_path, line_no, "qa", q, a, item))
            return

        m2 = CLOZE_RE.search(item)
        if m2:
            ans = m2.group(1).strip()
            prompt = CLOZE_RE.sub("____", item, count=1).strip()
            cid = card_id_for(rel_path, item)
            cards.append(Card(cid, rel_path, line_no, "cloze", prompt, ans, item))
            return

    # pass 1: look for explicit card section
    in_cards = False
    found_heading = False
    for idx, line in enumerate(lines, start=1):
        s = line.rstrip("\n")
        if not in_cards:
            if CARD_HEADING_RE.match(s.strip()):
                in_cards = True
                found_heading = True
            continue

        if HEADING_RE.match(s) and not CARD_HEADING_RE.match(s.strip()):
            break

        if not LIST_ITEM_RE.match(s):
            continue
        item = LIST_ITEM_RE.sub("", s)
        parse_item(item, idx)

    if found_heading:
        return cards

    # pass 2: fallback scan whole file
    for idx, line in enumerate(lines, start=1):
        s = line.rstrip("\n")
        if not LIST_ITEM_RE.match(s):
            continue
        item = LIST_ITEM_RE.sub("", s)
        parse_item(item, idx)

    return cards


def upsert_cards(con: sqlite3.Connection, cards: List[Card], init_due_ts: Optional[int] = None) -> Tuple[int, int]:
    created = 0
    updated = 0
    ts = now_ts()
    for c in cards:
        cur = con.execute("SELECT 1 FROM cards WHERE card_id=?", (c.card_id,)).fetchone()
        if cur is None:
            con.execute(
                "INSERT INTO cards(card_id,file_path,line_no,kind,prompt,answer,raw,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (c.card_id, c.file_path, c.line_no, c.kind, c.prompt, c.answer, c.raw, ts),
            )
            created += 1
        else:
            con.execute(
                "UPDATE cards SET file_path=?, line_no=?, kind=?, prompt=?, answer=?, raw=?, updated_at=? WHERE card_id=?",
                (c.file_path, c.line_no, c.kind, c.prompt, c.answer, c.raw, ts, c.card_id),
            )
            updated += 1

        # schedule row
        sch = con.execute("SELECT 1 FROM schedule WHERE card_id=?", (c.card_id,)).fetchone()
        if sch is None:
            due = init_due_ts if init_due_ts is not None else ts
            con.execute(
                "INSERT INTO schedule(card_id,ease,interval_days,reps,due_ts,last_review_ts,lapses) VALUES (?,?,?,?,?,?,?)",
                (c.card_id, 2.5, 0, 0, int(due), None, 0),
            )

    con.commit()
    return created, updated


def sm2_update(ease: float, interval_days: int, reps: int, q: int) -> Tuple[float, int, int, int]:
    # returns (new_ease, new_interval_days, new_reps, lapse_inc)
    if q < 3:
        # failed
        new_reps = 0
        new_interval = 1
        lapse = 1
    else:
        new_reps = reps + 1
        if new_reps == 1:
            new_interval = 1
        elif new_reps == 2:
            new_interval = 6
        else:
            new_interval = int(round(max(1, interval_days) * ease))
        lapse = 0

    # ease update
    new_ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if new_ease < 1.3:
        new_ease = 1.3

    return float(new_ease), int(new_interval), int(new_reps), int(lapse)


def select_due(con: sqlite3.Connection, limit: int | None, allow_future: bool = False) -> List[Tuple[str, str]]:
    """Select due cards.

    - allow_future=False: only cards with due_ts <= now
    - allow_future=True: earliest cards regardless of due

    If limit is None, return all matching rows.
    """

    ts = now_ts()

    if allow_future:
        sql = (
            "SELECT c.card_id, c.prompt "
            "FROM schedule s JOIN cards c ON c.card_id=s.card_id "
            "ORDER BY s.due_ts ASC"
        )
        params = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = con.execute(sql, params).fetchall()
    else:
        sql = (
            "SELECT c.card_id, c.prompt "
            "FROM schedule s JOIN cards c ON c.card_id=s.card_id "
            "WHERE s.due_ts <= ? "
            "ORDER BY s.due_ts ASC"
        )
        params = [ts]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = con.execute(sql, params).fetchall()

    return [(r[0], r[1]) for r in rows]


def cmd_scan(args) -> int:
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    total_cards = 0
    all_cards: List[Card] = []
    scanned_files: List[str] = []

    # include_draft is kept for backward compatibility; card files are independent.
    init_due = None
    if args.init_due == "now":
        init_due = now_ts()
    elif args.init_due == "tonight":
        # store as now; alignment to nightly time is handled by agent (text-level)
        init_due = now_ts()

    for md in iter_markdown_files(vault):
        try:
            txt = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            txt = md.read_text(encoding="utf-8", errors="ignore")

        lines = txt.splitlines(True)
        rel = normalize_rel_path(vault, md)
        scanned_files.append(rel)
        cards = extract_cards_from_lines(rel, lines)
        total_cards += len(cards)
        all_cards.extend(cards)

    deduped_cards, dropped_duplicates = dedupe_cards(con, all_cards)
    created, updated = upsert_cards(con, deduped_cards, init_due_ts=init_due)
    pruned_cards = prune_cards_for_scanned_files(con, scanned_files, [c.card_id for c in deduped_cards])
    status_files_updated = refresh_status_sections(
        con,
        vault,
        file_paths=sorted(set(scanned_files)) if scanned_files else None,
    )
    print(json.dumps({
        "vault": str(vault),
        "files_scanned": "auto",
        "cards_found": total_cards,
        "cards_kept": len(deduped_cards),
        "duplicates_ignored": len(dropped_duplicates),
        "cards_created": created,
        "cards_updated": updated,
        "cards_pruned": pruned_cards,
        "status_files_updated": status_files_updated,
        "duplicate_examples": dropped_duplicates[:10],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_quiz(args) -> int:
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    pp = pending_path(vault)
    if pp.exists() and not getattr(args, "force", False):
        print("上一组抽查还没答完/评分完成：请先回复答案（如 1=... 2=...），我会自动判分；或手动触发时加 --force 覆盖。")
        return 3

    items = select_due(con, args.count, allow_future=bool(args.allow_future))
    if not items:
        # fallback: give nearest future
        items = select_due(con, args.count, allow_future=True)

    if not items:
        print("题库为空：请先在 复习/记忆卡片/ 下生成卡片文件。")
        return 2

    quiz_id = f"q{now_ts()}"
    pending = {
        "quiz_id": quiz_id,
        "created_ts": now_ts(),
        "mode": "batch",
        "cursor": 0,
        "items": [
            {"n": i + 1, "card_id": cid, "prompt": prompt}
            for i, (cid, prompt) in enumerate(items)
        ],
    }
    pending_path(vault).write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    lines.append("记忆曲线抽查")
    lines.append("")
    for it in pending["items"]:
        lines.append(f"{it['n']}) {it['prompt']}")
    lines.append("")
    lines.append("请直接回复你的答案，我会自动判分并更新记忆曲线。回复示例：")
    lines.append("1=F=ma 2=180° 3=... …")
    lines.append("如果你不同意我的判分，指出题号即可，我会按你的反馈修正。")

    print("\n".join(lines))
    return 0


def _load_pending(vault: Path) -> Optional[dict]:
    pp = pending_path(vault)
    if not pp.exists():
        return None
    return json.loads(pp.read_text(encoding="utf-8"))


def _save_pending(vault: Path, pending: dict) -> None:
    pending_path(vault).write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")


def _pending_items(pending: dict) -> List[dict]:
    items = pending.get("items") or []
    # tolerate both [{n,card_id,prompt}] and [{card_id,prompt}]
    out = []
    for i, it in enumerate(items):
        if "n" not in it:
            it = dict(it)
            it["n"] = i + 1
        out.append(it)
    return out


def _format_one_question(pending: dict, vault: Path) -> str:
    items = _pending_items(pending)
    cursor = int(pending.get("cursor", 0) or 0)
    hold = None
    hp = hold_path(vault)
    if hp.exists():
        try:
            hold = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            hold = {"error": "failed_to_parse"}

    if cursor < 0:
        cursor = 0
    if cursor >= len(items):
        return "本轮复习已完成。"

    it = items[cursor]
    n = cursor + 1
    total = len(items)
    prompt = it.get("prompt") or ""

    lines = []
    lines.append(f"每日复习（第 {n}/{total} 题）")
    lines.append("")
    lines.append(prompt)
    lines.append("")
    lines.append("直接回复你的答案即可（不用写题号）。")
    lines.append("如果你想暂停：发送‘停止复习’。")
    return "\n".join(lines)


def cmd_next(args) -> int:
    """One-by-one review: print the current question.

    If no pending quiz exists, create one (count items) and print the first question.
    """
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    pending = _load_pending(vault)
    if pending is None or getattr(args, "force", False):
        if getattr(args, "all_due", False):
            items = select_due(con, None, allow_future=False)
        else:
            items = select_due(con, args.count, allow_future=False)

        if not items and getattr(args, "allow_future", False):
            items = select_due(con, args.count, allow_future=True)

        if not items:
            # No due cards (and no allow-future fallback). This is not an error.
            print("当前没有到期卡片。")
            return 0

        quiz_id = f"q{now_ts()}"
        pending = {
            "quiz_id": quiz_id,
            "created_ts": now_ts(),
            "mode": "one_by_one",
            "cursor": 0,
            "items": [
                {"n": i + 1, "card_id": cid, "prompt": prompt}
                for i, (cid, prompt) in enumerate(items)
            ],
        }
        _save_pending(vault, pending)

    # If cursor already finished, clear it.
    items = _pending_items(pending)
    cursor = int(pending.get("cursor", 0) or 0)
    hold = None
    hp = hold_path(vault)
    if hp.exists():
        try:
            hold = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            hold = {"error": "failed_to_parse"}

    if cursor >= len(items):
        try:
            pending_path(vault).unlink()
        except Exception:
            pass
        print("本轮复习已完成。")
        return 0

    print(_format_one_question(pending, vault))
    return 0




def _load_hold(vault: Path) -> Optional[dict]:
    hp = hold_path(vault)
    if not hp.exists():
        return None
    return json.loads(hp.read_text(encoding="utf-8"))


def _save_hold(vault: Path, hold: dict) -> None:
    hold_path(vault).write_text(json.dumps(hold, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_hold(args) -> int:
    """Hold a grading decision for the current question.

    This lets the agent show correctness + canonical answer first, then wait for user confirmation.
    """
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    pending = _load_pending(vault)
    if pending is None:
        print("没有 pending：请先 next 出题。")
        return 2

    items = _pending_items(pending)
    cursor = int(pending.get("cursor", 0) or 0)
    hold = None
    hp = hold_path(vault)
    if hp.exists():
        try:
            hold = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            hold = {"error": "failed_to_parse"}

    if cursor >= len(items):
        print("本轮复习已完成。")
        return 0

    it = items[cursor]
    card_id = it["card_id"]

    # ensure card exists
    row = con.execute("SELECT 1 FROM cards WHERE card_id=?", (card_id,)).fetchone()
    if row is None:
        print("该卡片不在 cards 表中：请先 scan 入库。")
        return 2

    hold = {
        "quiz_id": pending.get("quiz_id"),
        "cursor": cursor,
        "card_id": card_id,
        "q": int(args.q),
        "answer": args.answer,
        "held_ts": now_ts(),
    }
    _save_hold(vault, hold)

    print(json.dumps({
        "held": True,
        "cursor": cursor,
        "q": int(args.q),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_commit(args) -> int:
    """Commit the held grade to schedule (SM-2) and advance to next question."""
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    pending = _load_pending(vault)
    if pending is None:
        print("没有 pending。")
        return 2

    hold = _load_hold(vault)
    if hold is None:
        print("没有 hold：请先 hold 再 commit。")
        return 2

    items = _pending_items(pending)
    cursor = int(pending.get("cursor", 0) or 0)
    hold = None
    hp = hold_path(vault)
    if hp.exists():
        try:
            hold = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            hold = {"error": "failed_to_parse"}

    if cursor >= len(items):
        try:
            pending_path(vault).unlink()
        except Exception:
            pass
        try:
            hold_path(vault).unlink()
        except Exception:
            pass
        print("本轮复习已完成。")
        return 0

    it = items[cursor]
    card_id = it["card_id"]

    if int(hold.get("cursor")) != cursor or str(hold.get("card_id")) != str(card_id):
        print("hold 与当前题不匹配：请重新 hold。")
        return 2

    q = int(hold.get("q"))

    # Apply SM-2 update (same as grade1)
    ts = now_ts()
    row = con.execute(
        "SELECT ease, interval_days, reps, lapses FROM schedule WHERE card_id=?",
        (card_id,),
    ).fetchone()
    if row is None:
        print("该卡片未在 schedule 中：请先 scan 入库。")
        return 2

    ease, interval_days, reps, lapses = float(row[0]), int(row[1]), int(row[2]), int(row[3])
    new_ease, new_interval, new_reps, lapse_inc = sm2_update(ease, interval_days, reps, q)
    new_due = ts + new_interval * 86400
    con.execute(
        "UPDATE schedule SET ease=?, interval_days=?, reps=?, due_ts=?, last_review_ts=?, last_q=?, lapses=? WHERE card_id=?",
        (new_ease, new_interval, new_reps, int(new_due), int(ts), int(q), int(lapses + lapse_inc), card_id),
    )
    con.commit()
    status_files_updated = refresh_status_sections(con, vault, file_paths=file_paths_for_card_ids(con, [card_id]))

    # advance cursor
    cursor += 1
    pending["cursor"] = cursor

    # clear hold
    try:
        hold_path(vault).unlink()
    except Exception:
        pass

    cleared = False
    if cursor >= len(items):
        try:
            pending_path(vault).unlink()
            cleared = True
        except Exception:
            cleared = False
    else:
        _save_pending(vault, pending)

    due_count = con.execute("SELECT COUNT(*) FROM schedule WHERE due_ts <= ?", (ts,)).fetchone()[0]
    print(json.dumps({
        "committed": True,
        "q": q,
        "cursor": cursor,
        "total": len(items),
        "pending_cleared": cleared,
        "due_now": int(due_count),
        "status_files_updated": status_files_updated,
    }, ensure_ascii=False, indent=2))
    return 0

def cmd_grade1(args) -> int:
    """Apply a single quality score (0-5) to the current question, then advance cursor."""
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    pending = _load_pending(vault)
    if pending is None:
        print("没有 pending：请先 next/quiz 出题。")
        return 2

    items = _pending_items(pending)
    cursor = int(pending.get("cursor", 0) or 0)
    hold = None
    hp = hold_path(vault)
    if hp.exists():
        try:
            hold = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            hold = {"error": "failed_to_parse"}

    if cursor >= len(items):
        try:
            pending_path(vault).unlink()
        except Exception:
            pass
        print("本轮复习已完成。")
        return 0

    it = items[cursor]
    card_id = it["card_id"]
    q = int(args.q)

    ts = now_ts()
    row = con.execute(
        "SELECT ease, interval_days, reps, lapses FROM schedule WHERE card_id=?",
        (card_id,),
    ).fetchone()
    if row is None:
        print("该卡片未在 schedule 中：请先 scan 入库。")
        return 2

    ease, interval_days, reps, lapses = float(row[0]), int(row[1]), int(row[2]), int(row[3])
    new_ease, new_interval, new_reps, lapse_inc = sm2_update(ease, interval_days, reps, q)
    new_due = ts + new_interval * 86400
    con.execute(
        "UPDATE schedule SET ease=?, interval_days=?, reps=?, due_ts=?, last_review_ts=?, last_q=?, lapses=? WHERE card_id=?",
        (new_ease, new_interval, new_reps, int(new_due), int(ts), int(q), int(lapses + lapse_inc), card_id),
    )
    con.commit()
    status_files_updated = refresh_status_sections(con, vault, file_paths=file_paths_for_card_ids(con, [card_id]))

    # advance
    cursor += 1
    pending["cursor"] = cursor

    cleared = False
    if cursor >= len(items):
        try:
            pending_path(vault).unlink()
            cleared = True
        except Exception:
            cleared = False
    else:
        _save_pending(vault, pending)

    due_count = con.execute("SELECT COUNT(*) FROM schedule WHERE due_ts <= ?", (ts,)).fetchone()[0]
    print(json.dumps({
        "graded": 1,
        "q": q,
        "cursor": cursor,
        "total": len(items),
        "pending_cleared": cleared,
        "due_now": int(due_count),
        "status_files_updated": status_files_updated,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_clear(args) -> int:
    """Clear pending quiz (stop review). Also clears any held grading decision."""
    vault = vault_path_from_args(args)

    removed = []
    pp = pending_path(vault)
    if pp.exists():
        pp.unlink()
        removed.append("pending")

    hp = hold_path(vault)
    if hp.exists():
        hp.unlink()
        removed.append("hold")

    if removed:
        print(f"已停止复习：清理 {', '.join(removed)}。")
    else:
        print("没有正在进行的复习。")
    return 0



def parse_ratings(reply: str) -> Dict[int, int]:
    """Parse quality scores mapping like '1=5 2=3' (0-5)."""
    out: Dict[int, int] = {}
    for m in RATING_PAIR_RE.finditer(reply):
        n = int(m.group("n"))
        q = int(m.group("q"))
        out[n] = q
    return out


def cmd_pending(args) -> int:
    """Export pending quiz as JSON.

    With --with-answers, include canonical answers from the cards table.
    """
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    pp = pending_path(vault)
    if not pp.exists():
        print(json.dumps({"pending": False}, ensure_ascii=False, indent=2))
        return 0

    pending = json.loads(pp.read_text(encoding="utf-8"))
    items = pending.get("items") or []
    out_items = []
    for it in items:
        card_id = it["card_id"]
        row = con.execute(
            "SELECT kind, prompt, answer, file_path, line_no FROM cards WHERE card_id=?",
            (card_id,),
        ).fetchone()
        if row is None:
            continue
        kind, prompt, answer, file_path, line_no = row
        obj = {
            "n": it["n"],
            "card_id": card_id,
            "kind": kind,
            "prompt": prompt,
            "source": {"file_path": file_path, "line_no": int(line_no)},
        }
        if getattr(args, "with_answers", False):
            obj["answer"] = answer
        out_items.append(obj)

    cursor = int(pending.get("cursor", 0) or 0)
    hold = None
    hp = hold_path(vault)
    if hp.exists():
        try:
            hold = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            hold = {"error": "failed_to_parse"}

    mode = pending.get("mode")

    current = None
    if 0 <= cursor < len(out_items):
        current = out_items[cursor]

    print(json.dumps({
        "pending": True,
        "quiz_id": pending.get("quiz_id"),
        "created_ts": pending.get("created_ts"),
        "mode": mode,
        "cursor": cursor,
        "total": len(out_items),
        "current": current,
        "hold": hold,
        "items": out_items,
    }, ensure_ascii=False, indent=2))
    return 0


def apply_grades(con: sqlite3.Connection, card_ids_by_n: Dict[int, str], grades_by_n: Dict[int, int], clear_pending: bool, vault: Path) -> Tuple[int, List[int], int]:
    updated = 0
    missing: List[int] = []
    touched_card_ids: List[str] = []
    ts = now_ts()

    for n, card_id in card_ids_by_n.items():
        if n not in grades_by_n:
            missing.append(n)
            continue
        q = int(grades_by_n[n])

        row = con.execute(
            "SELECT ease, interval_days, reps, lapses FROM schedule WHERE card_id=?",
            (card_id,),
        ).fetchone()
        if row is None:
            continue
        ease, interval_days, reps, lapses = float(row[0]), int(row[1]), int(row[2]), int(row[3])
        new_ease, new_interval, new_reps, lapse_inc = sm2_update(ease, interval_days, reps, q)
        new_due = ts + new_interval * 86400
        con.execute(
            "UPDATE schedule SET ease=?, interval_days=?, reps=?, due_ts=?, last_review_ts=?, last_q=?, lapses=? WHERE card_id=?",
            (new_ease, new_interval, new_reps, int(new_due), int(ts), int(q), int(lapses + lapse_inc), card_id),
        )
        updated += 1
        touched_card_ids.append(card_id)

    con.commit()
    status_files_updated = refresh_status_sections(
        con,
        vault,
        file_paths=file_paths_for_card_ids(con, touched_card_ids),
    )

    if clear_pending and not missing:
        try:
            pending_path(vault).unlink()
        except Exception:
            pass

    return updated, missing, status_files_updated


def cmd_gradeq(args) -> int:
    """Apply grades (0-5) to the pending quiz.

    The grading itself is done by the agent; this command only updates SM-2 schedule.
    """
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    pp = pending_path(vault)
    if not pp.exists():
        print("没有 pending quiz：请先出题（quiz）。")
        return 2

    pending = json.loads(pp.read_text(encoding="utf-8"))
    items = pending.get("items") or []
    if not items:
        print("pending quiz 为空。")
        return 2

    grades = parse_ratings(args.q)
    card_ids_by_n = {int(it["n"]): it["card_id"] for it in items}

    updated, missing, status_files_updated = apply_grades(con, card_ids_by_n, grades, clear_pending=True, vault=vault)

    ts = now_ts()
    due_count = con.execute("SELECT COUNT(*) FROM schedule WHERE due_ts <= ?", (ts,)).fetchone()[0]
    print(json.dumps({
        "graded": updated,
        "missing": missing,
        "pending_cleared": (len(missing) == 0),
        "due_now": int(due_count),
        "status_files_updated": status_files_updated,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_grade(args) -> int:
    vault = vault_path_from_args(args)
    con = connect_db(vault)

    pp = pending_path(vault)
    if not pp.exists():
        print("没有 pending quiz：请先出题（quiz）。")
        return 2

    pending = json.loads(pp.read_text(encoding="utf-8"))
    items = pending.get("items") or []
    if not items:
        print("pending quiz 为空。")
        return 2

    ratings = parse_ratings(args.reply)

    updated = 0
    missing: List[int] = []
    touched_card_ids: List[str] = []

    ts = now_ts()
    for it in items:
        n = int(it["n"])
        if n not in ratings:
            missing.append(n)
            continue
        q = int(ratings[n])
        card_id = it["card_id"]

        row = con.execute(
            "SELECT ease, interval_days, reps, lapses FROM schedule WHERE card_id=?",
            (card_id,),
        ).fetchone()
        if row is None:
            continue
        ease, interval_days, reps, lapses = float(row[0]), int(row[1]), int(row[2]), int(row[3])
        new_ease, new_interval, new_reps, lapse_inc = sm2_update(ease, interval_days, reps, q)
        new_due = ts + new_interval * 86400
        con.execute(
            "UPDATE schedule SET ease=?, interval_days=?, reps=?, due_ts=?, last_review_ts=?, last_q=?, lapses=? WHERE card_id=?",
            (new_ease, new_interval, new_reps, int(new_due), int(ts), int(q), int(lapses + lapse_inc), card_id),
        )
        updated += 1
        touched_card_ids.append(card_id)

    con.commit()
    status_files_updated = refresh_status_sections(
        con,
        vault,
        file_paths=file_paths_for_card_ids(con, touched_card_ids),
    )

    if missing:
        # keep pending
        print(json.dumps({
            "graded": updated,
            "missing": missing,
            "note": "仍保留本次 pending；请补齐缺失题号的评分。",
            "status_files_updated": status_files_updated,
        }, ensure_ascii=False, indent=2))
        return 0

    # all graded -> clear pending
    try:
        pp.unlink()
    except Exception:
        pass

    due_count = con.execute("SELECT COUNT(*) FROM schedule WHERE due_ts <= ?", (ts,)).fetchone()[0]
    print(json.dumps({
        "graded": updated,
        "pending_cleared": True,
        "due_now": int(due_count),
        "status_files_updated": status_files_updated,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args) -> int:
    vault = vault_path_from_args(args)
    con = connect_db(vault)
    ts = now_ts()
    total = con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    due = con.execute("SELECT COUNT(*) FROM schedule WHERE due_ts <= ?", (ts,)).fetchone()[0]
    next_due = con.execute("SELECT MIN(due_ts) FROM schedule").fetchone()[0]
    print(json.dumps({
        "total_cards": int(total),
        "due_now": int(due),
        "next_due_ts": int(next_due) if next_due is not None else None,
        "pending_exists": pending_path(vault).exists(),
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sr_cli.py")
    p.add_argument("--vault", help="Obsidian vault path (or env OBSIDIAN_VAULT)")

    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("scan", help="scan vault for cards")
    s1.add_argument("--include-draft", action="store_true", help="include 状态: 初稿")
    s1.add_argument("--init-due", choices=["now", "tonight"], default="now")
    s1.set_defaults(func=cmd_scan)

    s2 = sub.add_parser("quiz", help="create a quiz from due cards")
    s2.add_argument("--count", type=int, default=8)
    s2.add_argument("--allow-future", action="store_true")
    s2.add_argument("--force", action="store_true", help="overwrite pending quiz")
    s2.set_defaults(func=cmd_quiz)

    s2b = sub.add_parser("next", help="one-by-one: show the current question (create pending if absent)")
    s2b.add_argument("--count", type=int, default=8, help="how many cards to include when starting a new session")
    s2b.add_argument("--all-due", action="store_true", help="include ALL due cards when starting a new session")
    s2b.add_argument("--allow-future", action="store_true", help="if no due cards, allow pulling nearest future cards")
    s2b.add_argument("--force", action="store_true", help="overwrite pending quiz")
    s2b.set_defaults(func=cmd_next)

    s2c = sub.add_parser("hold", help="hold a grading decision for the current question")
    s2c.add_argument("--q", required=True, help="quality 0-5")
    s2c.add_argument("--answer", default="", help="user answer text (optional, for traceability)")
    s2c.set_defaults(func=cmd_hold)

    s2d = sub.add_parser("commit", help="commit held grade to schedule and advance")
    s2d.set_defaults(func=cmd_commit)

    s2e = sub.add_parser("grade1", help="apply a single quality score (0-5) to the current question, then advance")
    s2e.add_argument("--q", required=True, help="quality 0-5")
    s2e.set_defaults(func=cmd_grade1)

    s2f = sub.add_parser("clear", help="clear pending quiz (stop review)")
    s2f.set_defaults(func=cmd_clear)

    s3 = sub.add_parser("pending", help="export pending quiz (optionally with answers)")
    s3.add_argument("--with-answers", action="store_true")
    s3.set_defaults(func=cmd_pending)

    s4 = sub.add_parser("gradeq", help="apply agent-computed grades (0-5) to pending quiz")
    s4.add_argument("--q", required=True, help="quality mapping like '1=5 2=3 3=0'")
    s4.set_defaults(func=cmd_gradeq)

    s5 = sub.add_parser("grade", help="grade pending quiz using self-ratings (legacy)")
    s5.add_argument("--reply", required=True, help="raw user reply text")
    s5.set_defaults(func=cmd_grade)

    s6 = sub.add_parser("status", help="show sr status")
    s6.set_defaults(func=cmd_status)

    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
