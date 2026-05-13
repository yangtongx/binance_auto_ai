"""One-way position mode execution."""

from __future__ import annotations

import logging
from typing import Callable

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.constants import LEG_POSITION_EPS_CONTRACTS, NET_POSITION_EPS_CONTRACTS
from futures_llm_bot.order_utils import amount_respects_limits, notional_to_amount, place_order, wait_for_legs
from futures_llm_bot.positions import PositionLegs, fetch_position_legs, mark_last_usdt, primary_exposure_notional_usdt
from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.session_risk import SessionRisk

logger = logging.getLogger(__name__)


def execute_oneway(
    ex: ccxt.binanceusdm,
    settings: Settings,
    signal: LLMSignal,
    *,
    session: SessionRisk | None,
    legs: PositionLegs,
    last: float,
    on_real_order: Callable[[], None] | None = None,
) -> None:
    symbol = settings.symbol
    pos = legs.signed_net()
    abs_notional = primary_exposure_notional_usdt(legs, last)

    if signal.action == Action.FLAT:
        if abs(pos) < NET_POSITION_EPS_CONTRACTS:
            logger.info("FLAT skipped — already flat")
            return
        side = "sell" if pos > 0 else "buy"
        amount = abs(float(ex.amount_to_precision(symbol, abs(pos))))
        params = {"reduceOnly": True}
        logger.info("FLAT %s %s amount=%s params=%s dry_run=%s", side, symbol, amount, params, settings.dry_run)
        place_order(
            ex, symbol, side, amount, params=params, dry_run=settings.dry_run, session=session, on_real_order=on_real_order
        )
        return

    requested = settings.max_notional_usdt * (signal.size_pct / 100.0)
    if requested <= 0:
        logger.info("directional trade skipped — requested notional<=0")
        return

    if signal.action == Action.LONG:
        if pos < -NET_POSITION_EPS_CONTRACTS:
            close_amt = abs(float(ex.amount_to_precision(symbol, abs(pos))))
            logger.info("close SHORT before LONG: buy reduceOnly amount=%s", close_amt)
            place_order(
                ex,
                symbol,
                "buy",
                close_amt,
                params={"reduceOnly": True},
                dry_run=settings.dry_run,
                session=session,
                on_real_order=on_real_order,
            )
            if not settings.dry_run:
                wait_for_legs(ex, symbol, settings, lambda lg: abs(lg.signed_net()) < LEG_POSITION_EPS_CONTRACTS)
            legs = fetch_position_legs(ex, symbol)
            last = mark_last_usdt(ex, symbol)
            abs_notional = primary_exposure_notional_usdt(legs, last)

        room = max(0.0, settings.max_notional_usdt - abs_notional)
        target_notional = min(requested, room)
        if target_notional <= 0:
            logger.info(
                "LONG skipped — at MAX_NOTIONAL_USDT cap (abs_notional≈%.4f, cap=%s)",
                abs_notional,
                settings.max_notional_usdt,
            )
            return

        amount, _ = notional_to_amount(ex, symbol, target_notional, last=last)
        if not amount_respects_limits(ex, symbol, amount, last=last):
            logger.info("LONG skipped — amount %s fails exchange min amount/cost", amount)
            return
        logger.info("LONG market buy amount=%s (notional≈%s USDT, room=%s)", amount, target_notional, room)
        place_order(ex, symbol, "buy", amount, params={}, dry_run=settings.dry_run, session=session, on_real_order=on_real_order)

    elif signal.action == Action.SHORT:
        if pos > NET_POSITION_EPS_CONTRACTS:
            close_amt = abs(float(ex.amount_to_precision(symbol, abs(pos))))
            logger.info("close LONG before SHORT: sell reduceOnly amount=%s", close_amt)
            place_order(
                ex,
                symbol,
                "sell",
                close_amt,
                params={"reduceOnly": True},
                dry_run=settings.dry_run,
                session=session,
                on_real_order=on_real_order,
            )
            if not settings.dry_run:
                wait_for_legs(ex, symbol, settings, lambda lg: abs(lg.signed_net()) < LEG_POSITION_EPS_CONTRACTS)
            legs = fetch_position_legs(ex, symbol)
            last = mark_last_usdt(ex, symbol)
            abs_notional = primary_exposure_notional_usdt(legs, last)

        room = max(0.0, settings.max_notional_usdt - abs_notional)
        target_notional = min(requested, room)
        if target_notional <= 0:
            logger.info(
                "SHORT skipped — at MAX_NOTIONAL_USDT cap (abs_notional≈%.4f, cap=%s)",
                abs_notional,
                settings.max_notional_usdt,
            )
            return

        amount, _ = notional_to_amount(ex, symbol, target_notional, last=last)
        if not amount_respects_limits(ex, symbol, amount, last=last):
            logger.info("SHORT skipped — amount %s fails exchange min amount/cost", amount)
            return
        logger.info("SHORT market sell amount=%s (notional≈%s USDT, room=%s)", amount, target_notional, room)
        place_order(ex, symbol, "sell", amount, params={}, dry_run=settings.dry_run, session=session, on_real_order=on_real_order)
