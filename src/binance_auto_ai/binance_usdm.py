"""币安 USDT-M 对外门面：聚合 execution / positions 的常用函数。"""

from binance_auto_ai.execution import (
    build_exchange,
    execute_signal,
    resolve_account_hedged,
    verify_position_mode_alignment,
)
from binance_auto_ai.positions import (
    fetch_futures_usdt_available_margin,
    fetch_futures_usdt_balance,
    fetch_futures_usdt_equity,
    fetch_position_contracts,
    fetch_position_legs,
    fetch_position_meta,
    format_account_context,
)

__all__ = [
    "build_exchange",
    "execute_signal",
    "fetch_futures_usdt_available_margin",
    "fetch_futures_usdt_balance",
    "fetch_futures_usdt_equity",
    "fetch_position_contracts",
    "fetch_position_legs",
    "fetch_position_meta",
    "format_account_context",
    "resolve_account_hedged",
    "verify_position_mode_alignment",
]
