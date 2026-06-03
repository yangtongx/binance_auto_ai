"""K 线工具：周期解析、未收盘 K 线剔除（避免 1m tick 在 5m 周期上重复触发交叉）。"""

from __future__ import annotations

import re
import time

_TF_RE = re.compile(r"^(\d+)([mhdw])$", re.IGNORECASE)


def timeframe_to_seconds(timeframe: str) -> int | None:
    m = _TF_RE.match((timeframe or "").strip())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    mult = {"m": 60, "h": 3600, "d": 86400, "w": 604800}.get(unit)
    if mult is None or n <= 0:
        return None
    return n * mult


def drop_incomplete_last_candle(ohlcv: list[list[float]], timeframe: str) -> list[list[float]]:
    """去掉仍在形成中的最后一根 K 线（实盘每分钟 tick 时尤其重要）。"""
    if len(ohlcv) < 2:
        return ohlcv
    tf_sec = timeframe_to_seconds(timeframe)
    if tf_sec is None:
        return ohlcv
    last_ts_ms = ohlcv[-1][0]
    try:
        open_ms = float(last_ts_ms)
    except (TypeError, ValueError):
        return ohlcv
    close_ms = open_ms + tf_sec * 1000
    if time.time() * 1000 < close_ms - 500:
        return ohlcv[:-1]
    return ohlcv
