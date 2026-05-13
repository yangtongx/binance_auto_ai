from __future__ import annotations

import logging
import math
from typing import Any, NamedTuple

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.constants import (
    LEG_POSITION_EPS_CONTRACTS,
    MAX_SANE_MARK_USDT,
    MIN_SANE_MARK_USDT,
    NET_POSITION_EPS_CONTRACTS,
)

logger = logging.getLogger(__name__)


class PositionLegs(NamedTuple):
    long_contracts: float
    short_contracts: float
    long_notional: float
    short_notional: float

    def signed_net(self) -> float:
        return self.long_contracts - self.short_contracts


def signed_position_contracts(position: dict[str, Any] | None) -> float:
    """Signed base-contract exposure from a CCXT unified position row.

    If ``side`` is missing, **do not** fall back to ``notional`` as contracts (units differ).
    """
    if not position:
        return 0.0
    contracts = position.get("contracts")
    if contracts is None:
        return 0.0
    side = (position.get("side") or "").lower()
    size = float(contracts)
    if side == "short":
        return -size
    if side == "long":
        return size
    if size == 0.0:
        return 0.0
    logger.warning(
        "position row has contracts=%s but no long/short side; ignoring (symbol=%s)",
        size,
        position.get("symbol"),
    )
    return 0.0


def fetch_position_legs(ex: ccxt.binanceusdm, symbol: str) -> PositionLegs:
    long_c = short_c = 0.0
    long_n = short_n = 0.0
    for p in ex.fetch_positions([symbol]):
        if p.get("symbol") != symbol:
            continue
        side = (p.get("side") or "").lower()
        c = float(p.get("contracts") or 0)
        raw_n = p.get("notional")
        try:
            n = float(raw_n) if raw_n is not None else 0.0
        except (TypeError, ValueError):
            n = 0.0
        if side == "long":
            long_c += c
            long_n = max(long_n, n)
        elif side == "short":
            short_c += c
            short_n = max(short_n, n)
        else:
            signed = signed_position_contracts(p)
            if signed > LEG_POSITION_EPS_CONTRACTS:
                long_c += abs(signed)
                long_n = max(long_n, n)
            elif signed < -LEG_POSITION_EPS_CONTRACTS:
                short_c += abs(signed)
                short_n = max(short_n, n)
    return PositionLegs(long_c, short_c, long_n, short_n)


def mark_last_usdt(ex: ccxt.binanceusdm, symbol: str) -> float:
    ticker = ex.fetch_ticker(symbol)
    last = float(ticker.get("last") or ticker.get("close") or 0)
    if not math.isfinite(last) or last <= 0 or last < MIN_SANE_MARK_USDT or last > MAX_SANE_MARK_USDT:
        raise RuntimeError(f"invalid or extreme last price: {last!r}")
    return last


def fetch_position_meta(ex: ccxt.binanceusdm, symbol: str) -> tuple[float, float]:
    legs = fetch_position_legs(ex, symbol)
    last = mark_last_usdt(ex, symbol)
    signed = legs.signed_net()
    abs_n = primary_exposure_notional_usdt(legs, last)
    return signed, abs_n


def fetch_position_contracts(ex: ccxt.binanceusdm, symbol: str) -> float:
    return fetch_position_legs(ex, symbol).signed_net()


def fetch_futures_usdt_equity(ex: ccxt.binanceusdm) -> float | None:
    try:
        bal = ex.fetch_balance()
    except ccxt.BaseError as e:
        logger.warning("fetch_balance failed (%s)", e)
        return None
    usdt = bal.get("USDT")
    if isinstance(usdt, dict):
        t = usdt.get("total")
    else:
        t = None
    if t is None:
        total = bal.get("total")
        if isinstance(total, dict):
            t = total.get("USDT")
    try:
        return float(t) if t is not None else None
    except (TypeError, ValueError):
        return None


def primary_exposure_notional_usdt(legs: PositionLegs, last: float) -> float:
    if legs.long_contracts > NET_POSITION_EPS_CONTRACTS and legs.short_contracts < NET_POSITION_EPS_CONTRACTS:
        return legs.long_notional if legs.long_notional > 0 else legs.long_contracts * last
    if legs.short_contracts > NET_POSITION_EPS_CONTRACTS and legs.long_contracts < NET_POSITION_EPS_CONTRACTS:
        return legs.short_notional if legs.short_notional > 0 else legs.short_contracts * last
    if legs.long_contracts < NET_POSITION_EPS_CONTRACTS and legs.short_contracts < NET_POSITION_EPS_CONTRACTS:
        return 0.0
    return max(
        legs.long_notional if legs.long_notional > 0 else legs.long_contracts * last,
        legs.short_notional if legs.short_notional > 0 else legs.short_contracts * last,
    )


def long_leg_notional_usdt(legs: PositionLegs, last: float) -> float:
    if legs.long_contracts < LEG_POSITION_EPS_CONTRACTS:
        return 0.0
    return legs.long_notional if legs.long_notional > 0 else legs.long_contracts * last


def short_leg_notional_usdt(legs: PositionLegs, last: float) -> float:
    if legs.short_contracts < LEG_POSITION_EPS_CONTRACTS:
        return 0.0
    return legs.short_notional if legs.short_notional > 0 else legs.short_contracts * last


def format_account_context(
    ex: ccxt.binanceusdm,
    settings: Settings,
    *,
    account_hedged: bool,
) -> str:
    legs = fetch_position_legs(ex, settings.symbol)
    last = mark_last_usdt(ex, settings.symbol)
    eq = fetch_futures_usdt_equity(ex)
    ln = legs.long_notional if legs.long_notional > 0 else legs.long_contracts * last
    sn = legs.short_notional if legs.short_notional > 0 else legs.short_contracts * last
    eq_s = f"{eq:.4f}" if eq is not None else "unknown"
    mode = "hedge (LONG/SHORT legs)" if account_hedged else "one-way"
    return (
        f"Account: USDT-M futures, position mode={mode}.\n"
        f"Wallet USDT (total, best-effort): {eq_s}\n"
        f"Position legs for {settings.symbol}: "
        f"LONG contracts={legs.long_contracts} (~{ln:.4f} USDT notional), "
        f"SHORT contracts={legs.short_contracts} (~{sn:.4f} USDT notional), "
        f"net_signed_contracts={legs.signed_net():.8f}.\n"
        f"Mark/last≈{last:.6f} USDT per 1 contract (approximate where notional missing)."
    )
