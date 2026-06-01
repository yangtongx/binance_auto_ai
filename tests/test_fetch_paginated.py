from __future__ import annotations

from unittest.mock import MagicMock, patch

from binance_auto_ai.backtest.data import fetch_ohlcv_ccxt_paginated


def test_fetch_ohlcv_ccxt_paginated_two_chunks() -> None:
    m_ex = MagicMock()
    m_ex.load_markets = MagicMock()

    def fetch_side_effect(symbol, timeframe, limit, params=None):
        _ = symbol
        _ = timeframe
        _ = limit
        p = params or {}
        et = p.get("endTime")
        if et is None:
            return [[3000.0, 1, 1, 1, 100.0, 1], [3100.0, 1, 1, 1, 101.0, 1]]
        return [[2800.0, 1, 1, 1, 99.0, 1], [2900.0, 1, 1, 1, 99.5, 1]]

    m_ex.fetch_ohlcv = MagicMock(side_effect=fetch_side_effect)

    with patch("binance_auto_ai.backtest.data._new_binance_usdm_exchange", return_value=m_ex):
        rows = fetch_ohlcv_ccxt_paginated(
            symbol="BTC/USDT:USDT",
            timeframe="1h",
            max_bars=4,
            testnet=False,
            page_size=2,
            max_requests=10,
        )

    assert len(rows) == 4
    assert [r[0] for r in rows] == [2800.0, 2900.0, 3000.0, 3100.0]
    assert m_ex.fetch_ohlcv.call_count == 2
