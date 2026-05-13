"""Hedge (dual-side) position mode execution for Binance USDT-M."""

from __future__ import annotations

import logging
from typing import Callable

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.constants import LEG_POSITION_EPS_CONTRACTS, NET_POSITION_EPS_CONTRACTS
from futures_llm_bot.order_utils import amount_respects_limits, notional_to_amount, place_order, wait_for_legs
from futures_llm_bot.positions import PositionLegs, fetch_position_legs, long_leg_notional_usdt, mark_last_usdt, short_leg_notional_usdt
from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.session_risk import SessionRisk

logger = logging.getLogger(__name__)


def execute_hedged(
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

    if signal.action == Action.FLAT:
        for attempt in range(3):
            legs = fetch_position_legs(ex, symbol)
            if legs.long_contracts < NET_POSITION_EPS_CONTRACTS and legs.short_contracts < NET_POSITION_EPS_CONTRACTS:
                if attempt == 0:
                    logger.info("FLAT skipped — both legs flat")
                return
            if legs.long_contracts > LEG_POSITION_EPS_CONTRACTS:
                amt = float(ex.amount_to_precision(symbol, legs.long_contracts))
                logger.info("HEDGE FLAT close LONG amount=%s (attempt %s)", amt, attempt + 1)
                place_order(
                    ex,
                    symbol,
                    "sell",
                    amt,
                    params={"positionSide": "LONG", "reduceOnly": True},
                    dry_run=settings.dry_run,
                    session=session,
                    on_real_order=on_real_order,
                )
                if not settings.dry_run:
                    wait_for_legs(ex, symbol, settings, lambda lg: lg.long_contracts < LEG_POSITION_EPS_CONTRACTS)
            legs = fetch_position_legs(ex, symbol)
            if legs.short_contracts > LEG_POSITION_EPS_CONTRACTS:
                amt = float(ex.amount_to_precision(symbol, legs.short_contracts))
                logger.info("HEDGE FLAT close SHORT amount=%s (attempt %s)", amt, attempt + 1)
                place_order(
                    ex,
                    symbol,
                    "buy",
                    amt,
                    params={"positionSide": "SHORT", "reduceOnly": True},
                    dry_run=settings.dry_run,
                    session=session,
                    on_real_order=on_real_order,
                )
                if not settings.dry_run:
                    wait_for_legs(ex, symbol, settings, lambda lg: lg.short_contracts < LEG_POSITION_EPS_CONTRACTS)
        legs = fetch_position_legs(ex, symbol)
        if legs.long_contracts > LEG_POSITION_EPS_CONTRACTS or legs.short_contracts > LEG_POSITION_EPS_CONTRACTS:
            logger.warning("HEDGE FLAT may be incomplete — legs still non-zero after retries")
        return

    requested = settings.max_notional_usdt * (signal.size_pct / 100.0)
    if requested <= 0:
        logger.info("directional trade skipped — requested notional<=0")
        return

    if signal.action == Action.LONG:
        if legs.short_contracts > LEG_POSITION_EPS_CONTRACTS:
            close_amt = float(ex.amount_to_precision(symbol, legs.short_contracts))
            logger.info("HEDGE close SHORT leg before LONG amount=%s", close_amt)
            place_order(
                ex,
                symbol,
                "buy",
                close_amt,
                params={"positionSide": "SHORT", "reduceOnly": True},
                dry_run=settings.dry_run,
                session=session,
                on_real_order=on_real_order,
            )
            if not settings.dry_run:
                wait_for_legs(ex, symbol, settings, lambda lg: lg.short_contracts < LEG_POSITION_EPS_CONTRACTS)
            legs = fetch_position_legs(ex, symbol)
            last = mark_last_usdt(ex, symbol)

        long_n = long_leg_notional_usdt(legs, last)
        room = max(0.0, settings.max_notional_usdt - long_n)
        target_notional = min(requested, room)
        if target_notional <= 0:
            logger.info("HEDGE LONG skipped — long leg at cap (long_notional≈%.4f)", long_n)
            return
        amount, _ = notional_to_amount(ex, symbol, target_notional, last=last)
        if not amount_respects_limits(ex, symbol, amount, last=last):
            logger.info("HEDGE LONG skipped — amount %s fails min amount/cost", amount)
            return
        logger.info("HEDGE LONG market buy amount=%s positionSide=LONG", amount)
        place_order(
            ex,
            symbol,
            "buy",
            amount,
            params={"positionSide": "LONG"},
            dry_run=settings.dry_run,
            session=session,
            on_real_order=on_real_order,
        )

    elif signal.action == Action.SHORT:
        if legs.long_contracts > LEG_POSITION_EPS_CONTRACTS:
            close_amt = float(ex.amount_to_precision(symbol, legs.long_contracts))
            logger.info("HEDGE close LONG leg before SHORT amount=%s", close_amt)
            place_order(
                ex,
                symbol,
                "sell",
                close_amt,
                params={"positionSide": "LONG", "reduceOnly": True},
                dry_run=settings.dry_run,
                session=session,
                on_real_order=on_real_order,
            )
            if not settings.dry_run:
                wait_for_legs(ex, symbol, settings, lambda lg: lg.long_contracts < LEG_POSITION_EPS_CONTRACTS)
            legs = fetch_position_legs(ex, symbol)
            last = mark_last_usdt(ex, symbol)

        short_n = short_leg_notional_usdt(legs, last)
        room = max(0.0, settings.max_notional_usdt - short_n)
        target_notional = min(requested, room)
        if target_notional <= 0:
            logger.info("HEDGE SHORT skipped — short leg at cap (short_notional≈%.4f)", short_n)
            return
        amount, _ = notional_to_amount(ex, symbol, target_notional, last=last)
        if not amount_respects_limits(ex, symbol, amount, last=last):
            logger.info("HEDGE SHORT skipped — amount %s fails min amount/cost", amount)
            return
        logger.info("HEDGE SHORT market sell amount=%s positionSide=SHORT", amount)
        place_order(
            ex,
            symbol,
            "sell",
            amount,
            params={"positionSide": "SHORT"},
            dry_run=settings.dry_run,
            session=session,
            on_real_order=on_real_order,
        )
