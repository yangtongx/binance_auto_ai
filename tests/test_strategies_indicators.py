from __future__ import annotations

from futures_llm_bot.backtest.engine import run_backtest
from futures_llm_bot.backtest.strategies import _rsi_series
from futures_llm_bot.strategy_factory import build_strategy_for_backtest, min_bars_for_backtest


def test_rsi_series_first_value_at_period() -> None:
    # Monotone up → high RSI at end
    c = [100.0 + i * 0.1 for i in range(30)]
    s = _rsi_series(c, 14)
    assert s[13] is None
    assert s[14] is not None
    assert s[-1] is not None
    assert s[-1] > 50.0


def test_min_bars_for_macd_orders_slow_plus_signal() -> None:
    assert min_bars_for_backtest("macd", slow=26, macd_signal=9) == 26 + 9 + 10


def test_backtest_rsi_runs() -> None:
    ohlcv: list[list[float]] = []
    base = 50_000.0
    for i in range(80):
        c = base + (i % 20) * 10.0
        ts = i * 60_000
        ohlcv.append([ts, c, c + 5, c - 5, c, 100.0])
    r = run_backtest(
        ohlcv,
        build_strategy_for_backtest("rsi", fast=10, slow=30, rsi_period=14),
        initial_cash_usdt=50_000.0,
        max_notional_usdt=5_000.0,
    )
    assert len(r.equity_curve) == len(ohlcv)
