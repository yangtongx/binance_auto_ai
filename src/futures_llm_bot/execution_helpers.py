"""Shared order primitives for one-way and hedge execution paths."""

from __future__ import annotations

import logging
from typing import Callable

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.order_utils import (
    amount_respects_limits,
    format_amount_limits_skip,
    notional_to_amount,
    place_order,
    wait_for_legs,
)
from futures_llm_bot.positions import PositionLegs, fetch_position_legs, mark_last_usdt
from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.session_risk import SessionRisk

logger = logging.getLogger(__name__)


def directional_notional_or_skip(
    settings: Settings,
    signal: LLMSignal,
    *,
    equity_usdt: float | None = None,
    available_margin_usdt: float | None = None,
) -> float | None:
    """Return USDT notional intent for LONG/SHORT; log and return ``None`` if not applicable or zero."""
    if signal.action not in (Action.LONG, Action.SHORT):
        return None
    pct = signal.size_pct / 100.0
    if settings.position_sizing == "equity_leverage":
        if equity_usdt is None or equity_usdt <= 0:
            logger.warning(
                "directional trade skipped — wallet USDT total unavailable for POSITION_SIZING=equity_leverage"
            )
            return None
        base = float(equity_usdt)
        label = "wallet_total"
    elif settings.position_sizing == "available_margin_leverage":
        if available_margin_usdt is None or available_margin_usdt <= 0:
            logger.warning(
                "directional trade skipped — available USDT margin unavailable for "
                "POSITION_SIZING=available_margin_leverage"
            )
            return None
        base = float(available_margin_usdt)
        label = "available_margin"
    elif settings.position_sizing == "fixed":
        requested = settings.max_notional_usdt * pct
        if requested <= 0:
            logger.info("directional trade skipped — requested notional<=0")
            return None
        return requested
    else:
        logger.warning("directional trade skipped — unknown POSITION_SIZING=%r", settings.position_sizing)
        return None

    requested = base * settings.leverage * pct
    logger.info(
        "position sizing %s: %s=%.4f leverage=%.0f size_pct=%.2f%% → notional≈%.4f USDT "
        "(hard cap MAX_NOTIONAL_USDT=%.2f)",
        settings.position_sizing,
        label,
        base,
        settings.leverage,
        signal.size_pct,
        requested,
        settings.max_notional_usdt,
    )
    if requested <= 0:
        logger.info("directional trade skipped — requested notional<=0")
        return None
    return requested


def close_reduce_only_and_refresh(
    ex: ccxt.binanceusdm,
    symbol: str,
    settings: Settings,
    session: SessionRisk | None,
    on_real_order: Callable[[], None] | None,
    *,
    side: str,
    amount: float,
    params: dict,
    wait_until: Callable[[PositionLegs], bool],
    log_message: str,
) -> tuple[PositionLegs, float]:
    """Submit reduce-only close, optionally wait for legs, then refresh legs + mark."""
    logger.info(log_message)
    place_order(
        ex,
        symbol,
        side,
        amount,
        params=params,
        dry_run=settings.dry_run,
        session=session,
        on_real_order=on_real_order,
    )
    if not settings.dry_run:
        wait_for_legs(ex, symbol, settings, wait_until)
    legs = fetch_position_legs(ex, symbol, dry_run=settings.dry_run)
    last = mark_last_usdt(ex, symbol)
    return legs, last


def open_market_within_notional_cap(
    ex: ccxt.binanceusdm,
    symbol: str,
    settings: Settings,
    session: SessionRisk | None,
    on_real_order: Callable[[], None] | None,
    *,
    last: float,
    requested: float,
    exposure_abs: float,
    side: str,
    order_params: dict,
    success_log: str,
    skip_cap_log: str,
    skip_limits_log: str,
) -> None:
    """
    Compute ``room`` under ``MAX_NOTIONAL_USDT``, clamp ``requested``, then market ``place_order``.

    ``exposure_abs`` is whichever leg/notional already consumes the cap (abs net, long leg, or short leg).
    """
    room = max(0.0, settings.max_notional_usdt - exposure_abs)
    target_notional = min(requested, room)
    if target_notional <= 0:
        logger.info(skip_cap_log)
        return
    amount, _ = notional_to_amount(ex, symbol, target_notional, last=last)
    if not amount_respects_limits(ex, symbol, amount, last=last):
        logger.warning(
            "%s — %s",
            skip_limits_log % (amount,),
            format_amount_limits_skip(
                ex, symbol, amount=amount, last=last, notional_usdt=target_notional
            ),
        )
        return
    logger.info(success_log, amount, target_notional, room)
    place_order(
        ex,
        symbol,
        side,
        amount,
        params=order_params,
        dry_run=settings.dry_run,
        session=session,
        on_real_order=on_real_order,
    )
