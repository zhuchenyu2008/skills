# Screenshot parsing notes (仓位截图)

Goal: Extract **symbol**, **position qty**, **entry price** (and optionally mark price / liquidation / leverage) from a trading-app screenshot.

## Heuristics

- Prefer the **Position** / **仓位** section, not order history.
- Qty / size keywords:
  - English: `Size`, `Position`, `Qty`, `Contracts`, `Amount`
  - Chinese: `数量`, `仓位`, `持仓`, `张`, `合约`, `方向`
- Entry keywords:
  - English: `Entry`, `Avg Entry`, `Entry Price`
  - Chinese: `开仓均价`, `开仓价`, `入场价`, `均价`
- Symbol formats:
  - Spot-ish: `BTCUSDT`, `BTC/USDT`
  - Coinbase-style: `BTC-USD`
  - If screenshot says `BTCUSDT`, treat as `BTC-USD` for pricing (best-effort).

## If OCR/vision is ambiguous

Ask 1-2 targeted questions only:
- “我识别到 qty 可能是 -0.0042（做空），entry 可能是 67840，对吗？”
- “标的是 BTC 吗？如果不是 BTC，把交易对写一下（例如 ETHUSDT）。”

## Normalization

- `qty > 0` => LONG; `qty < 0` => SHORT.
- Entry/price assume quote currency is USD/USDT.
