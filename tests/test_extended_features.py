from __future__ import annotations

import numpy as np

from futures_llm_bot.backtest.indicators import ichimoku_signal_state, volume_profile_poc
from futures_llm_bot.config import Settings
from futures_llm_bot.strategy_factory import build_live_strategy, min_bars_for_backtest
from futures_llm_bot.telegram_notify import send_telegram_message


def test_min_bars_ichimoku_uses_senkou() -> None:
    assert min_bars_for_backtest("ichimoku", senkou_b=52) == 57
    assert min_bars_for_backtest("ichi", senkou_b=52) == 57


def test_volume_profile_poc_in_range() -> None:
    h = np.array([10.0, 11.0, 10.5], dtype=np.float64)
    low = np.array([9.0, 10.0, 10.0], dtype=np.float64)
    c = np.array([9.5, 10.5, 10.3], dtype=np.float64)
    v = np.array([100.0, 200.0, 150.0], dtype=np.float64)
    got = volume_profile_poc(h, low, c, v, bins=10)
    assert got is not None
    poc, lo, hi = got
    assert lo <= poc <= hi


def test_ichimoku_signal_state_warmup() -> None:
    n = 60
    h = np.linspace(100, 110, n)
    low = h - 1.0
    c = (h + low) / 2.0
    st = ichimoku_signal_state(h, low, c, tenkan=9, kijun=26, senkou_b=52)
    assert st is not None
    assert len(st) == 8


def test_settings_ichimoku_valid() -> None:
    s = Settings(signal_source="strategy", strategy_name="ichimoku")
    assert s.strategy_ichimoku_tenkan == 9


def test_build_ichimoku_strategy_on_bar() -> None:
    settings = Settings(signal_source="strategy", strategy_name="ichi")
    strat = build_live_strategy(settings)
    ohlcv: list[list[float]] = []
    base = 100.0
    for i in range(60):
        ts = i * 60_000
        hi = base + i * 0.1
        lo = hi - 0.5
        cl = (hi + lo) / 2.0
        ohlcv.append([ts, cl - 0.05, hi, lo, cl, 10.0])
    sig = strat.on_bar(len(ohlcv) - 1, ohlcv)
    assert sig.action.value in ("long", "short", "hold", "flat")


def test_telegram_empty_settings_noop() -> None:
    s = Settings()
    send_telegram_message(s, "hello")
