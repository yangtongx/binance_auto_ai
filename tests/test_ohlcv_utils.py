from __future__ import annotations

import time

from binance_auto_ai.ohlcv_utils import drop_incomplete_last_candle, timeframe_to_seconds


def test_timeframe_to_seconds() -> None:
    assert timeframe_to_seconds("5m") == 300
    assert timeframe_to_seconds("1h") == 3600


def test_drop_incomplete_last_candle() -> None:
    tf_sec = 300
    now_ms = int(time.time() * 1000)
    forming_open = now_ms - tf_sec * 500
    ohlcv = [
        [forming_open - tf_sec * 1000, 1, 1, 1, 1, 1],
        [forming_open, 2, 2, 2, 2, 2],
    ]
    closed = drop_incomplete_last_candle(ohlcv, "5m")
    assert len(closed) == 1
    assert closed[0][0] == ohlcv[0][0]
