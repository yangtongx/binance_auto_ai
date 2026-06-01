from __future__ import annotations

import numpy as np

from binance_auto_ai.backtest.indicators import (
    MACDStream,
    RSIWilderStream,
    SMACrossStream,
    macd_signal_last,
    rsi_wilder_series,
)
from binance_auto_ai.backtest.strategies import (
    MacdCrossStrategy,
    RsiThresholdStrategy,
    SMACrossStrategy,
)


def test_incremental_sma_matches_batch_random_walk() -> None:
    rng = np.random.default_rng(42)
    c = (10000 + np.cumsum(rng.normal(0, 5, 800))).tolist()
    batch_sig = []
    for i in range(len(c)):
        st = SMACrossStrategy(fast=5, slow=15)
        ohlcv = [[j * 60_000, x, x, x, x, 1.0] for j, x in enumerate(c[: i + 1])]
        batch_sig.append(st.on_bar(i, ohlcv).action.value)

    st2 = SMACrossStrategy(fast=5, slow=15)
    st2.reset()
    inc_sig = []
    for i in range(len(c)):
        ohlcv = [[j * 60_000, x, x, x, x, 1.0] for j, x in enumerate(c[: i + 1])]
        inc_sig.append(st2.on_bar(i, ohlcv).action.value)

    assert inc_sig == batch_sig


def test_incremental_rsi_stream_matches_numpy_series() -> None:
    rng = np.random.default_rng(1)
    c = (1000 + np.cumsum(rng.normal(0, 2.0, 200))).astype(np.float64)
    p = 14
    full = rsi_wilder_series(c, p)
    st = RSIWilderStream(p)
    for n in range(p + 1, c.size):
        st.ensure(c[:n].tolist())
        r_inc = st.rsi()
        r_full = float(full[n - 1])
        assert r_inc is not None
        assert abs(r_inc - r_full) < 1e-6, (n, r_inc, r_full)


def test_incremental_macd_matches_last_cross() -> None:
    rng = np.random.default_rng(7)
    c = (5000 + np.cumsum(rng.normal(0, 3.0, 300))).astype(np.float64)
    fast, slow, sig = 12, 26, 9
    st = MACDStream(fast, slow, sig)
    batch = []
    for n in range(slow + sig + 2, c.size):
        st.ensure(c[:n].tolist())
        x = st.cross()
        ref = macd_signal_last(c[:n], fast, slow, sig)
        assert x is not None and ref is not None
        batch.append(max(abs(x[i] - ref[i]) for i in range(4)))
    assert max(batch) < 1e-4


def test_macd_strategy_parity_Reset_each_bar() -> None:
    """MacdCrossStrategy with reset each step vs monotonic stream (default)."""
    rng = np.random.default_rng(0)
    c = (8000 + np.cumsum(rng.normal(0, 4.0, 120))).astype(np.float64)
    ohlcv_full = [[i * 60_000, float(v), float(v), float(v), float(v), 1.0] for i, v in enumerate(c)]

    mono = MacdCrossStrategy(fast=12, slow=26, signal_period=9)
    mono.reset()
    inc_actions = [mono.on_bar(i, ohlcv_full[: i + 1]).action.value for i in range(len(c))]

    batch_actions = []
    for i in range(len(c)):
        m = MacdCrossStrategy(fast=12, slow=26, signal_period=9)
        m.reset()
        batch_actions.append(m.on_bar(i, ohlcv_full[: i + 1]).action.value)

    assert inc_actions == batch_actions
