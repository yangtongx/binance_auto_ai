"""One-way position mode execution."""

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
from futures_llm_bot.order_utils import place_order
from futures_llm_bot.positions import PositionLegs, primary_exposure_notional_usdt
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

    requested = directional_notional_or_skip(settings, signal)
    if requested is None:
        return

    if signal.action == Action.LONG:
        if pos < -NET_POSITION_EPS_CONTRACTS:
            close_amt = abs(float(ex.amount_to_precision(symbol, abs(pos))))
            legs, last = close_reduce_only_and_refresh(
                ex,
                symbol,
                settings,
                session,
                on_real_order,
                side="buy",
                amount=close_amt,
                params={"reduceOnly": True},
                wait_until=lambda lg: abs(lg.signed_net()) < LEG_POSITION_EPS_CONTRACTS,
                log_message=f"close SHORT before LONG: buy reduceOnly amount={close_amt}",
            )
            abs_notional = primary_exposure_notional_usdt(legs, last)

        open_market_within_notional_cap(
            ex,
            symbol,
            settings,
            session,
            on_real_order,
            last=last,
            requested=requested,
            exposure_abs=abs_notional,
            side="buy",
            order_params={},
            success_log="LONG market buy amount=%s (notional≈%s USDT, room=%s)",
            skip_cap_log=(
                f"LONG skipped — at MAX_NOTIONAL_USDT cap "
                f"(abs_notional≈{abs_notional:.4f}, cap={settings.max_notional_usdt})"
            ),
            skip_limits_log="LONG skipped — amount %s fails exchange min amount/cost",
        )

    elif signal.action == Action.SHORT:
        if pos > NET_POSITION_EPS_CONTRACTS:
            close_amt = abs(float(ex.amount_to_precision(symbol, abs(pos))))
            legs, last = close_reduce_only_and_refresh(
                ex,
                symbol,
                settings,
                session,
                on_real_order,
                side="sell",
                amount=close_amt,
                params={"reduceOnly": True},
                wait_until=lambda lg: abs(lg.signed_net()) < LEG_POSITION_EPS_CONTRACTS,
                log_message=f"close LONG before SHORT: sell reduceOnly amount={close_amt}",
            )
            abs_notional = primary_exposure_notional_usdt(legs, last)

        open_market_within_notional_cap(
            ex,
            symbol,
            settings,
            session,
            on_real_order,
            last=last,
            requested=requested,
            exposure_abs=abs_notional,
            side="sell",
            order_params={},
            success_log="SHORT market sell amount=%s (notional≈%s USDT, room=%s)",
            skip_cap_log=(
                f"SHORT skipped — at MAX_NOTIONAL_USDT cap "
                f"(abs_notional≈{abs_notional:.4f}, cap={settings.max_notional_usdt})"
            ),
            skip_limits_log="SHORT skipped — amount %s fails exchange min amount/cost",
        )