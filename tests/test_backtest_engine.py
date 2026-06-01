from __future__ import annotations

from binance_auto_ai.backtest.engine import run_backtest
from binance_auto_ai.backtest.strategies import SMACrossStrategy


def _synth_uptrend(n: int = 120, base: float = 10_000.0) -> list[list[float]]:
    """Monotone rising closes so fast SMA stays above slow after warmup → few reversals."""
    ohlcv: list[list[float]] = []
    for i in range(n):
        c = base + i * 50.0
        ts = i * 60_000
        ohlcv.append([ts, c, c + 10, c - 10, c, 100.0])
    return ohlcv


def test_backtest_sma_runs_and_records_equity() -> None:
    o = _synth_uptrend()
    r = run_backtest(o, SMACrossStrategy(fast=3, slow=8), initial_cash_usdt=50_000.0, max_notional_usdt=5_000.0)
    assert len(r.equity_curve) == len(o)
    assert isinstance(r.total_return_pct, float)
    assert isinstance(r.max_drawdown_pct, float)
