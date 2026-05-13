"""Load OHLCV for backtests (CCXT or CSV)."""

from __future__ import annotations

import csv
from pathlib import Path

import ccxt

OHLCVRow = list[float]  # [ts_ms, o, h, l, c, v]


def fetch_ohlcv_ccxt(
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    testnet: bool = True,
) -> list[OHLCVRow]:
    """Pull history from Binance USDM (testnet by default). Requires network."""
    ex = ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "future"}})
    if testnet:
        ex.set_sandbox_mode(True)
    ex.load_markets()
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    return [list(map(float, row)) for row in raw]


def load_ohlcv_csv(path: Path | str) -> list[OHLCVRow]:
    """CSV columns: timestamp_ms,open,high,low,close,volume (header row optional)."""
    p = Path(path)
    rows: list[OHLCVRow] = []
    with p.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for idx, line in enumerate(reader):
            if not line or all(not c.strip() for c in line):
                continue
            if idx == 0 and line[0].lower() in ("timestamp_ms", "time", "ts", "timestamp"):
                continue
            rows.append(list(map(float, line[:6])))
    return rows
