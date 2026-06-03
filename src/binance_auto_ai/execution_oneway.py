"""单向持仓模式下单：净仓 long/short，平仓用 reduceOnly，无 positionSide。"""

from __future__ import annotations

import logging
from typing import Callable

import ccxt

from binance_auto_ai.config import Settings
from binance_auto_ai.constants import LEG_POSITION_EPS_CONTRACTS, NET_POSITION_EPS_CONTRACTS
from binance_auto_ai.execution_helpers import (
    close_reduce_only_and_refresh,
    directional_notional_or_skip,
    open_market_within_notional_cap,
)
from binance_auto_ai.order_utils import place_order
from binance_auto_ai.positions import PositionLegs, fetch_position_legs, primary_exposure_notional_usdt
from binance_auto_ai.schemas import Action, LLMSignal
from binance_auto_ai.session_risk import SessionRisk

logger = logging.getLogger(__name__)


def execute_oneway(
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
    """执行 flat / long / short；反向信号时先 reduceOnly 平掉对立仓再开仓。"""
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

    requested = directional_notional_or_skip(
        settings,
        signal,
        equity_usdt=equity_usdt,
        available_margin_usdt=available_margin_usdt,
    )
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

        legs = fetch_position_legs(ex, symbol, dry_run=settings.dry_run)
        abs_notional = primary_exposure_notional_usdt(legs, last)
        if legs.signed_net() > NET_POSITION_EPS_CONTRACTS:
            logger.info("LONG skipped — already long (no add-on)")
            return

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
            available_margin_usdt=available_margin_usdt,
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

        legs = fetch_position_legs(ex, symbol, dry_run=settings.dry_run)
        abs_notional = primary_exposure_notional_usdt(legs, last)
        if legs.signed_net() < -NET_POSITION_EPS_CONTRACTS:
            logger.info("SHORT skipped — already short (no add-on)")
            return

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
            available_margin_usdt=available_margin_usdt,
        )