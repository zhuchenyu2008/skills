#!/usr/bin/env python3
"""Send one position snapshot email.

Designed to be called from cron every N minutes.

This script supports a *legacy mail format* used earlier:
Subject:
  [BTC仓位] 当前价 67,094 | 当前盈利 3.135 USDT | 15分钟下行
Body:
  时间(UTC): ...
  标的: BTCUSDT (CryptoCompare)
  当前价格: 67,093.66

  仓位数量(BTC): -0.0042
  开仓均价: 67,840.00
  当前盈利(USDT，未含手续费/资金费): 3.1346

  15分钟变化: -207.44 (-0.308%)
  15分钟趋势: 下行 (斜率≈-0.0220%/min)

Notes:
- This script never chooses recipients; caller must pass --to.
- Email sending is delegated to workspace email/send_email.py.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Tuple

import os
import urllib.request


WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", "/opt/openclaw/workspace"))
SEND_EMAIL = WORKSPACE / "email" / "send_email.py"


@dataclass
class PriceQuote:
    symbol: str
    price: Decimal
    source: str


def _fetch_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "openclaw-btc-position-watch/1.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def norm_symbol(symbol: str) -> str:
    """Normalize user symbol into either BTCUSDT or BASE-QUOTE.

    Legacy watcher used BTCUSDT + CryptoCompare.
    We keep supporting:
    - BTCUSDT / ETHUSDT ... (preferred for legacy format)
    - BTC-USD / BTCUSD
    """

    s = symbol.strip().upper().replace("_", "-")
    s = s.replace("/", "")
    if "-" in s:
        return s
    return s


def split_base_quote(symbol: str) -> tuple[str, str, str]:
    """Return (display_symbol, base, quote).

    - If symbol like BTCUSDT -> (BTCUSDT, BTC, USDT)
    - If symbol like BTC-USD -> (BTC-USD, BTC, USD)
    """

    s = norm_symbol(symbol)
    if "-" in s:
        base, quote = s.split("-", 1)
        return s, base, quote
    # best-effort: treat trailing 3-4 letters as quote
    if s.endswith("USDT"):
        return s, s[:-4], "USDT"
    if s.endswith("USD"):
        return s, s[:-3], "USD"
    # default
    return s + "USD", s, "USD"


def get_spot_price(symbol: str) -> PriceQuote:
    disp, base, quote = split_base_quote(symbol)

    # Legacy format prefers CryptoCompare (to match earlier emails)
    try:
        data = _fetch_json(f"https://min-api.cryptocompare.com/data/price?fsym={base}&tsyms={quote}")
        amt = Decimal(str(data[quote]))
        # keep display like BTCUSDT for legacy
        return PriceQuote(symbol=disp, price=amt, source="CryptoCompare")
    except Exception:
        pass

    # Fallback: Coinbase for -USD style pairs
    if quote == "USD":
        cb = f"{base}-USD"
        try:
            data = _fetch_json(f"https://api.coinbase.com/v2/prices/{cb}/spot")
            amt = Decimal(str(data["data"]["amount"]))
            return PriceQuote(symbol=cb, price=amt, source="Coinbase")
        except Exception:
            pass

    raise RuntimeError(f"Failed to fetch spot price for {symbol}")


def get_15m_trend(symbol: str) -> Tuple[Optional[Decimal], Optional[Decimal], str]:
    """Return (delta_price, delta_pct, source).

    Uses CryptoCompare histominute; returns (None, None, src) if unavailable.
    """

    disp, base, quote = split_base_quote(symbol)
    try:
        url = (
            "https://min-api.cryptocompare.com/data/v2/histominute"
            f"?fsym={base}&tsym={quote}&limit=15&aggregate=1"
        )
        data = _fetch_json(url)
        arr = data.get("Data", {}).get("Data", [])
        if len(arr) < 2:
            return None, None, "CryptoCompare"
        first = Decimal(str(arr[0].get("close")))
        last = Decimal(str(arr[-1].get("close")))
        if first == 0:
            return None, None, "CryptoCompare"
        delta = last - first
        pct = (delta / first) * Decimal("100")
        return delta, pct, "CryptoCompare"
    except Exception:
        return None, None, "CryptoCompare"


def fmt_money(x: Decimal) -> str:
    q = x.quantize(Decimal("0.01"))
    return f"{q:,}"


def fmt_price(x: Decimal) -> str:
    if x >= 1:
        return fmt_money(x)
    q = x.quantize(Decimal("0.000001"))
    return f"{q}"


def compute_pnl(qty: Decimal, entry: Decimal, price: Decimal) -> Tuple[Decimal, Optional[Decimal]]:
    pnl = (price - entry) * qty
    pct = None
    try:
        notional = abs(entry * qty)
        if notional != 0:
            pct = (pnl / notional) * Decimal("100")
    except Exception:
        pct = None
    return pnl, pct


def run_send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    if not SEND_EMAIL.exists():
        raise RuntimeError(f"Missing {SEND_EMAIL} (expected in workspace)")
    cmd = [sys.executable, str(SEND_EMAIL), "--to", to, "--subject", subject, "--text", text]
    if html:
        cmd += ["--html", html]
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--symbol", default="BTC-USD")
    ap.add_argument("--qty", required=True, help="Position size. Positive=long, negative=short. E.g. -0.0042")
    ap.add_argument("--entry", required=True, help="Entry price, in quote currency (e.g. 67840)")
    ap.add_argument("--tag", default="", help="Optional label shown in subject")
    ap.add_argument("--note", default="", help="Optional note appended to body")

    args = ap.parse_args()

    try:
        qty = Decimal(str(args.qty))
        entry = Decimal(str(args.entry))
    except InvalidOperation:
        raise SystemExit("--qty/--entry must be numbers")

    quote = get_spot_price(args.symbol)
    display_symbol, base_asset, _quote_asset = split_base_quote(quote.symbol)
    pnl, _pnl_pct = compute_pnl(qty=qty, entry=entry, price=quote.price)

    # Dynamic label: 盈利 / 亏损 / 持平
    pnl_label = "盈利" if pnl > 0 else "亏损" if pnl < 0 else "持平"

    # Legacy formatting
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

    delta, delta_pct, trend_src = get_15m_trend(quote.symbol)
    if delta is None or delta_pct is None:
        delta = Decimal("0")
        delta_pct = Decimal("0")

    trend_dir = "下行" if delta_pct < 0 else "上行" if delta_pct > 0 else "横盘"
    slope = (delta_pct / Decimal("15")).quantize(Decimal("0.0001"))

    # Subject: keep the original verbose format; encoding is handled in send_email.py.
    subj_price = f"{int(quote.price.to_integral_value(rounding='ROUND_HALF_UP')):,}"
    subj_profit = abs(pnl).quantize(Decimal("0.001"))
    subject = f"[{base_asset}仓位] 当前价 {subj_price} | 当前{pnl_label} {subj_profit} USDT | 15分钟{trend_dir}"

    # Body: keep legacy fields but present them more "dashboard-like"
    price_now = quote.price.quantize(Decimal('0.01'))
    entry_q = entry.quantize(Decimal('0.01'))
    pnl_q = pnl.quantize(Decimal('0.0001'))

    diff = (quote.price - entry).quantize(Decimal('0.01'))
    diff_sign = "+" if diff > 0 else ""  # keep '-' from Decimal

    delta_q = delta.quantize(Decimal('0.01'))
    delta_pct_q = delta_pct.quantize(Decimal('0.001'))

    # Plain-text fallback (keep it compact)
    lines = [
        f"时间(UTC): {now}",
        f"标的: {quote.symbol} ({trend_src})",
        f"当前价格: {price_now}",
        f"开仓均价: {entry_q} (差值: {diff_sign}{diff})",
        f"仓位数量({base_asset}): {qty}",
        f"当前{pnl_label}(USDT， 未含手续费/资金费): {pnl_q}",
        f"15分钟变化: {delta_q} ({delta_pct_q}%)",
        f"15分钟趋势: {trend_dir} (斜率≈{slope}%/min)",
    ]
    text = "\n".join(lines) + "\n"

    # HTML body ("web-like" card)
    is_up = delta_pct > 0
    is_down = delta_pct < 0
    trend_accent = "#16a34a" if is_up else "#dc2626" if is_down else "#6b7280"  # green/red/gray
    trend_label = "上行" if is_up else "下行" if is_down else "横盘"

    # PnL coloring: 盈利=绿，亏损=红，持平=灰
    pnl_is_up = pnl > 0
    pnl_is_down = pnl < 0
    pnl_accent = "#16a34a" if pnl_is_up else "#dc2626" if pnl_is_down else "#6b7280"

    html = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif;">
    <div style="max-width:560px;margin:0 auto;padding:16px;">
      <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;box-shadow:0 6px 20px rgba(0,0,0,0.06);">
        <div style="padding:14px 16px;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;justify-content:space-between;gap:12px;">
          <div>
            <div style="font-size:14px;color:#111827;font-weight:700;">{base_asset} 仓位提醒</div>
            <div style="font-size:12px;color:#6b7280;">{quote.symbol} · {now} UTC · {trend_src}</div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;background:{trend_accent};color:#ffffff;padding:6px 10px;border-radius:9999px;font-weight:900;font-size:12px;white-space:nowrap;line-height:1;">
            <span style="opacity:0.95;">15分钟</span>
            <span style="font-size:13px;">{trend_label}</span>
          </div>
        </div>

        <div style="padding:16px;">
          <div style="display:flex;gap:12px;flex-wrap:wrap;">
            <div style="flex:1;min-width:240px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:12px;">
              <div style="font-size:12px;color:#6b7280;">当前价格</div>
              <div style="font-size:28px;color:#111827;font-weight:800;line-height:1.1;">{price_now}</div>
              <div style="margin-top:6px;font-size:12px;color:#6b7280;">开仓 {entry_q} · 差值 <span style=\"color:{pnl_accent};font-weight:700;\">{diff_sign}{diff}</span></div>
            </div>
            <div style="flex:1;min-width:240px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:12px;">
              <div style="font-size:12px;color:#6b7280;">当前{pnl_label} (USDT)</div>
              <div style="font-size:28px;color:{pnl_accent};font-weight:900;line-height:1.1;">{pnl_q}</div>
              <div style="margin-top:6px;font-size:12px;color:#6b7280;">仓位数量 {qty} {base_asset}</div>
              <div style="margin-top:2px;font-size:12px;color:#6b7280;">未含手续费/资金费</div>
            </div>
          </div>

          <div style="margin-top:12px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:12px;">
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline;">
              <div>
                <div style="font-size:12px;color:#6b7280;">15分钟变化</div>
                <div style="font-size:16px;font-weight:800;color:#111827;">{delta_q} <span style=\"color:{trend_accent};font-weight:800;\">({delta_pct_q}%)</span></div>
              </div>
              <div style="text-align:right;">
                <div style="font-size:12px;color:#6b7280;">斜率</div>
                <div style="font-size:16px;font-weight:800;color:#111827;">{slope}%/min</div>
              </div>
            </div>
            <div style="margin-top:10px;height:8px;background:#e5e7eb;border-radius:999px;overflow:hidden;">
              <div style="height:100%;width:{min(100, max(5, int(abs(float(delta_pct_q)) * 10)))}%;background:{trend_accent};"></div>
            </div>
          </div>
        </div>

        <div style="padding:12px 16px;border-top:1px solid #e5e7eb;font-size:11px;color:#6b7280;">
          数据来源：{trend_src}。本邮件为盯盘提醒，不构成投资建议。
        </div>
      </div>
    </div>
  </body>
</html>
"""

    run_send_email(args.to, subject, text, html=html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
