"""回测子包对外导出：run_backtest、BacktestResult、示例策略。"""

from __future__ import annotations

from binance_auto_ai.backtest.engine import BacktestResult, run_backtest
from binance_auto_ai.backtest.strategies import SMACrossStrategy

__all__ = [
    "BacktestResult",
    "SMACrossStrategy",
    "run_backtest",
]
