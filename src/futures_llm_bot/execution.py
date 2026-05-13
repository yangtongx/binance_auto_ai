"""Exchange bootstrap and trade execution (delegates one-way vs hedge)."""

from __future__ import annotations

import logging
from typing import Callable

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.execution_hedge import execute_hedged
from futures_llm_bot.execution_oneway import execute_oneway
from futures_llm_bot.positions import fetch_position_legs, mark_last_usdt
from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.session_risk import SessionRisk

logger = logging.getLogger(__name__)


def build_exchange(settings: Settings) -> ccxt.binanceusdm:
    ex = ccxt.binanceusdm(
        {
            "apiKey": settings.binance_api_key,
            "secret": settings.binance_api_secret,
            "enableRateLimit": True,
            "timeout": settings.exchange_timeout_ms,
            "options": {"defaultType": "future"},
        }
    )
    if settings.binance_testnet:
        ex.set_sandbox_mode(True)
    return ex


def resolve_account_hedged(ex: ccxt.binanceusdm, settings: Settings) -> bool:
    mode = settings.position_mode.lower().strip()
    if mode == "oneway":
        return False
    if mode == "hedge":
        return True
    if mode != "auto":
        raise ValueError(f"POSITION_MODE must be auto|oneway|hedge, got {settings.position_mode!r}")
    if not settings.binance_api_key:
        return False
    try:
        out = ex.fetchPositionMode()
        return bool(out.get("hedged"))
    except ccxt.BaseError as e:
        logger.warning("fetchPositionMode failed (%s); assuming one-way", e)
        return False


def execute_signal(
    ex: ccxt.binanceusdm,
    settings: Settings,
    signal: LLMSignal,
    *,
    account_hedged: bool,
    session: SessionRisk | None = None,
    on_real_order: Callable[[], None] | None = None,
) -> None:
    symbol = settings.symbol
    legs = fetch_position_legs(ex, symbol)
    last = mark_last_usdt(ex, symbol)

    if signal.action == Action.HOLD:
        logger.info("HOLD — no order")
        return

    if account_hedged:
        execute_hedged(
            ex, settings, signal, session=session, legs=legs, last=last, on_real_order=on_real_order
        )
        return

    execute_oneway(
        ex, settings, signal, session=session, legs=legs, last=last, on_real_order=on_real_order
    )
