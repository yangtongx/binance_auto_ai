"""Exchange bootstrap and trade execution (delegates one-way vs hedge)."""

from __future__ import annotations

import logging
from typing import Callable

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.exchange_env import (
    apply_binance_usdm_environment,
    apply_ccxt_proxy_config,
    configure_binance_usdm_exchange,
)
from futures_llm_bot.execution_hedge import execute_hedged
from futures_llm_bot.execution_oneway import execute_oneway
from futures_llm_bot.positions import fetch_position_legs, mark_last_usdt
from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.session_risk import SessionRisk

logger = logging.getLogger(__name__)


def build_exchange(settings: Settings) -> ccxt.binanceusdm:
    cfg: dict = {
        "apiKey": settings.binance_api_key,
        "secret": settings.binance_api_secret,
        "enableRateLimit": True,
        "timeout": settings.exchange_timeout_ms,
        "options": {},
    }
    apply_ccxt_proxy_config(settings, cfg)
    ex = ccxt.binanceusdm(cfg)
    configure_binance_usdm_exchange(ex)
    apply_binance_usdm_environment(ex, testnet=settings.binance_testnet)
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
    symbol: str | None = None,
    equity_usdt: float | None = None,
    available_margin_usdt: float | None = None,
    session: SessionRisk | None = None,
    on_real_order: Callable[[], None] | None = None,
) -> None:
    if signal.action == Action.HOLD:
        logger.info("HOLD — no order")
        return

    active_settings = settings.model_copy(update={"symbol": symbol}) if symbol else settings
    symbol = active_settings.symbol
    legs = fetch_position_legs(ex, symbol, dry_run=active_settings.dry_run)
    last = mark_last_usdt(ex, symbol)

    if account_hedged:
        execute_hedged(
            ex,
            active_settings,
            signal,
            session=session,
            legs=legs,
            last=last,
            equity_usdt=equity_usdt,
            available_margin_usdt=available_margin_usdt,
            on_real_order=on_real_order,
        )
        return

    execute_oneway(
        ex,
        active_settings,
        signal,
        session=session,
        legs=legs,
        last=last,
        equity_usdt=equity_usdt,
        available_margin_usdt=available_margin_usdt,
        on_real_order=on_real_order,
    )
