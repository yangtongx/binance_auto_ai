"""Binance USDT-M integration: re-exports from focused submodules."""

from futures_llm_bot.execution import (
    build_exchange,
    execute_signal,
    resolve_account_hedged,
)
from futures_llm_bot.positions import (
    fetch_futures_usdt_equity,
    fetch_position_contracts,
    fetch_position_legs,
    fetch_position_meta,
    format_account_context,
)

__all__ = [
    "build_exchange",
    "execute_signal",
    "fetch_futures_usdt_equity",
    "fetch_position_contracts",
    "fetch_position_legs",
    "fetch_position_meta",
    "format_account_context",
    "resolve_account_hedged",
]
