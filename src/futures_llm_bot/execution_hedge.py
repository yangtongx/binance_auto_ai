"""Hedge (dual-side) position mode execution for Binance USDT-M."""

from __future__ import annotations

import logging
from typing import Callable

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.constants import LEG_POSITION_EPS_CONTRACTS, NET_POSITION_EPS_CONTRACTS
from futures_llm_bot.execution_helpers import (
    close_reduce_only_and_refresh,
    directional_notional_or_skip,
    open_market_within_notional_cap,
)
from futures_llm_bot.order_utils import place_order, wait_for_legs
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
    equity_usdt: float | None = None,
    available_margin_usdt: float | None = None,
    on_real_order: Callable[[], None] | None = None,
) -> None:
    symbol = settings.symbol

    if signal.action == Action.FLAT:
        for attempt in range(3):
            legs = fetch_position_legs(ex, symbol, dry_run=settings.dry_run)
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
            legs = fetch_position_legs(ex, symbol, dry_run=settings.dry_run)
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
        legs = fetch_position_legs(ex, symbol, dry_run=settings.dry_run)
        if legs.long_contracts > LEG_POSITION_EPS_CONTRACTS or legs.short_contracts > LEG_POSITION_EPS_CONTRACTS:
            logger.warning("HEDGE FLAT may be incomplete — legs still non-zero after retries")
        return

    requested = directional_notional_or_skip(
        settings,
        signal,
        equity_usdt=equity_usdt,
        available_margin_usdt=available_margin_usdt,
    )
    if requested is None:
        return

    if signal.action == Action.LONG:
        if legs.short_contracts > LEG_POSITION_EPS_CONTRACTS:
            close_amt = float(ex.amount_to_precision(symbol, legs.short_contracts))
            legs, last = close_reduce_only_and_refresh(
                ex,
                symbol,
                settings,
                session,
                on_real_order,
                side="buy",
                amount=close_amt,
                params={"positionSide": "SHORT", "reduceOnly": True},
                wait_until=lambda lg: lg.short_contracts < LEG_POSITION_EPS_CONTRACTS,
                log_message=f"HEDGE close SHORT leg before LONG amount={close_amt}",
            )

        long_n = long_leg_notional_usdt(legs, last)
        open_market_within_notional_cap(
            ex,
            symbol,
            settings,
            session,
            on_real_order,
            last=last,
            requested=requested,
            exposure_abs=long_n,
            side="buy",
            order_params={"positionSide": "LONG"},
            success_log="HEDGE LONG market buy amount=%s (notional≈%s USDT, room=%s)",
            skip_cap_log=(f"HEDGE LONG skipped — long leg at cap (long_notional≈{long_n:.4f})"),
            skip_limits_log="HEDGE LONG skipped — amount %s fails min amount/cost",
        )

    elif signal.action == Action.SHORT:
        if legs.long_contracts > LEG_POSITION_EPS_CONTRACTS:
            close_amt = float(ex.amount_to_precision(symbol, legs.long_contracts))
            legs, last = close_reduce_only_and_refresh(
                ex,
                symbol,
                settings,
                session,
                on_real_order,
                side="sell",
                amount=close_amt,
                params={"positionSide": "LONG", "reduceOnly": True},
                wait_until=lambda lg: lg.long_contracts < LEG_POSITION_EPS_CONTRACTS,
                log_message=f"HEDGE close LONG leg before SHORT amount={close_amt}",
            )

        short_n = short_leg_notional_usdt(legs, last)
        open_market_within_notional_cap(
            ex,
            symbol,
            settings,
            session,
            on_real_order,
            last=last,
            requested=requested,
            exposure_abs=short_n,
            side="sell",
            order_params={"positionSide": "SHORT"},
            success_log="HEDGE SHORT market sell amount=%s (notional≈%s USDT, room=%s)",
            skip_cap_log=(f"HEDGE SHORT skipped — short leg at cap (short_notional≈{short_n:.4f})"),
            skip_limits_log="HEDGE SHORT skipped — amount %s fails min amount/cost",
        )
