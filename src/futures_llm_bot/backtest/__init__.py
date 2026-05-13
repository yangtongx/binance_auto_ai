"""Backtesting: historical OHLCV → deterministic strategy → simulated fills."""

from __future__ import annotations

from futures_llm_bot.backtest.engine import BacktestResult, run_backtest
from futures_llm_bot.backtest.strategies import SMACrossStrategy

__all__ = [
    "BacktestResult",
    "SMACrossStrategy",
    "run_backtest",
]
