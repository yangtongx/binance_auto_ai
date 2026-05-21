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


def fetch_exchange_hedged(ex: ccxt.binanceusdm) -> bool | None:
    """Return True if Binance account is dual-side (hedge); None if API check failed."""
    try:
        out = ex.fetchPositionMode()
        return bool(out.get("hedged"))
    except ccxt.BaseError as e:
        logger.warning("fetchPositionMode failed (%s)", e)
        return None


def verify_position_mode_alignment(ex: ccxt.binanceusdm, settings: Settings) -> None:
    """Fail fast when POSITION_MODE=oneway|hedge disagrees with the exchange account."""
    forced = settings.position_mode.lower().strip()
    if forced not in ("oneway", "hedge") or not settings.binance_api_key:
        return
    actual = fetch_exchange_hedged(ex)
    if actual is None:
        return
    want_hedged = forced == "hedge"
    if actual == want_hedged:
        return
    exchange_mode = "双向持仓 (hedge)" if actual else "单向持仓 (one-way)"
    env_mode = "hedge" if want_hedged else "oneway"
    raise SystemExit(
        f"POSITION_MODE={env_mode} 与币安账户不一致（当前为 {exchange_mode}）。"
        f" 请改 POSITION_MODE=auto，或在币安合约设置里切换持仓模式；"
        f" 错误 -4061 即由此引起。"
    )


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
    actual = fetch_exchange_hedged(ex)
    if actual is None:
        return False
    return actual


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
