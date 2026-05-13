"""Helpers for sizing, polling, and placing CCXT orders (Binance USDT-M)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.positions import PositionLegs, fetch_position_legs, mark_last_usdt
from futures_llm_bot.session_risk import SessionRisk

logger = logging.getLogger(__name__)


def notional_to_amount(
    ex: ccxt.binanceusdm,
    symbol: str,
    notional_usdt: float,
    *,
    last: float | None = None,
) -> tuple[float, float]:
    last_px = float(last) if last is not None else mark_last_usdt(ex, symbol)
    amount = notional_usdt / last_px
    return float(ex.amount_to_precision(symbol, amount)), last_px


def amount_respects_limits(ex: ccxt.binanceusdm, symbol: str, amount: float, *, last: float) -> bool:
    if amount <= 0:
        return False
    market = ex.market(symbol)
    limits = market.get("limits") or {}
    amt_limits = limits.get("amount") or {}
    min_amt = amt_limits.get("min")
    if min_amt is not None and amount < float(min_amt):
        return False
    cost_limits = limits.get("cost") or {}
    min_cost = cost_limits.get("min")
    if min_cost is not None and amount * last < float(min_cost):
        return False
    return True


def wait_for_legs(
    ex: ccxt.binanceusdm,
    symbol: str,
    settings: Settings,
    ok: Callable[[PositionLegs], bool],
) -> None:
    deadline = time.monotonic() + settings.position_poll_timeout_sec
    while time.monotonic() < deadline:
        if ok(fetch_position_legs(ex, symbol)):
            return
        time.sleep(settings.position_poll_interval_sec)
    logger.warning("position poll timed out (timeout=%ss) symbol=%s", settings.position_poll_timeout_sec, symbol)


def place_order(
    ex: ccxt.binanceusdm,
    symbol: str,
    side: str,
    amount: float,
    *,
    params: dict[str, Any],
    dry_run: bool,
    session: SessionRisk | None,
    on_real_order: Callable[[], None] | None = None,
) -> None:
    logger.info("ORDER %s %s amount=%s params=%s dry_run=%s", side, symbol, amount, params, dry_run)
    if dry_run:
        return
    ex.create_order(symbol, "market", side, amount, params=params)
    if on_real_order is not None:
        on_real_order()
    if session is not None:
        session.record_executed_order()
