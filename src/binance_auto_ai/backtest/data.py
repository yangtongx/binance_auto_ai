"""回测数据：从币安 CCXT 拉取或读取 CSV OHLCV。"""

from __future__ import annotations

import csv
from pathlib import Path

import ccxt

from binance_auto_ai.exchange_env import (
    apply_binance_usdm_environment,
    configure_binance_usdm_exchange,
    load_binance_usdm_markets,
)

OHLCVRow = list[float]  # [时间戳ms, 开, 高, 低, 收, 量]


def _new_binance_usdm_exchange(*, testnet: bool) -> ccxt.binanceusdm:
    ex = ccxt.binanceusdm({"enableRateLimit": True, "options": {}})
    configure_binance_usdm_exchange(ex)
    apply_binance_usdm_environment(ex, testnet=testnet)
    return ex


def fetch_ohlcv_ccxt(
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    testnet: bool = True,
) -> list[OHLCVRow]:
    """Pull history from Binance USDM (testnet by default). Requires network."""
    ex = _new_binance_usdm_exchange(testnet=testnet)
    load_binance_usdm_markets(ex)
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    return [list(map(float, row)) for row in raw]


def fetch_ohlcv_ccxt_paginated(
    *,
    symbol: str,
    timeframe: str,
    max_bars: int,
    testnet: bool = True,
    page_size: int = 1500,
    max_requests: int = 500,
) -> list[OHLCVRow]:
    """Fetch up to ``max_bars`` most recent candles by paging backward with Binance ``endTime``.

    Binance caps ``limit`` per call (typically 1500). Uses public klines (no API key required).
    Returns rows oldest → newest, length ≤ ``max_bars`` (last segment is the most recent window).
    """
    if max_bars < 1:
        return []
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    ex = _new_binance_usdm_exchange(testnet=testnet)
    load_binance_usdm_markets(ex)

    out: list[OHLCVRow] = []
    end_time: int | None = None
    stuck = 0
    for _ in range(max_requests):
        if len(out) >= max_bars:
            break
        need = min(page_size, max_bars - len(out))
        params: dict = {}
        if end_time is not None:
            params["endTime"] = end_time
        raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=need, params=params)
        if not raw:
            break
        batch = [list(map(float, row)) for row in raw]
        if out and batch[-1][0] >= out[0][0]:
            stuck += 1
            if stuck > 5:
                break
            end_time = int(batch[0][0]) - 1
            if end_time <= 0:
                break
            continue
        stuck = 0
        out = batch + out
        end_time = int(batch[0][0]) - 1
        if end_time <= 0:
            break

    if len(out) > max_bars:
        out = out[-max_bars:]
    return out


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
