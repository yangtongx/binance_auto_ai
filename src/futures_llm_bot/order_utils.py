"""下单工具：名义↔张数、最小下单量、place_order（含 DRY_RUN）与持仓轮询。"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import ccxt

from futures_llm_bot.config import Settings
from futures_llm_bot.positions import PositionLegs, fetch_position_legs, mark_last_usdt
from futures_llm_bot.session_risk import SessionRisk

logger = logging.getLogger(__name__)


def min_order_amount(ex: ccxt.binanceusdm, symbol: str) -> float:
    """Smallest order size in contracts (from CCXT limits or amount precision step)."""
    market = ex.market(symbol)
    limits = market.get("limits") or {}
    amt_limits = limits.get("amount") or {}
    min_amt = amt_limits.get("min")
    if min_amt is not None:
        return float(min_amt)
    prec = market.get("precision") or {}
    amt_prec = prec.get("amount")
    if isinstance(amt_prec, (int, float)) and float(amt_prec) > 0:
        # 币安 USDM 常在此暴露步长（如 0.001 BTC）
        if isinstance(amt_prec, int) and amt_prec >= 0:
            return float(10 ** (-amt_prec))
        return float(amt_prec)
    return 0.0


def min_order_notional_usdt(ex: ccxt.binanceusdm, symbol: str, *, last: float | None = None) -> float:
    last_px = float(last) if last is not None else mark_last_usdt(ex, symbol)
    return min_order_amount(ex, symbol) * last_px


def amount_to_precision_or_zero(ex: ccxt.binanceusdm, symbol: str, amount: float) -> float:
    """Round to exchange step; return 0 if result is dust below ``min_order_amount``."""
    if amount <= 0:
        return 0.0
    rounded = float(ex.amount_to_precision(symbol, amount))
    if rounded <= 0:
        return 0.0
    min_amt = min_order_amount(ex, symbol)
    if min_amt > 0 and rounded + 1e-15 < min_amt:
        return 0.0
    return rounded


def notional_to_amount(
    ex: ccxt.binanceusdm,
    symbol: str,
    notional_usdt: float,
    *,
    last: float | None = None,
) -> tuple[float, float]:
    last_px = float(last) if last is not None else mark_last_usdt(ex, symbol)
    amount = notional_usdt / last_px
    return amount_to_precision_or_zero(ex, symbol, amount), last_px


def amount_respects_limits(ex: ccxt.binanceusdm, symbol: str, amount: float, *, last: float) -> bool:
    if amount <= 0:
        return False
    min_amt = min_order_amount(ex, symbol)
    if min_amt > 0 and amount + 1e-15 < min_amt:
        return False
    market = ex.market(symbol)
    limits = market.get("limits") or {}
    cost_limits = limits.get("cost") or {}
    min_cost = cost_limits.get("min")
    if min_cost is not None and amount * last < float(min_cost):
        return False
    return True


def format_amount_limits_skip(
    ex: ccxt.binanceusdm,
    symbol: str,
    *,
    amount: float,
    last: float,
    notional_usdt: float | None = None,
) -> str:
    min_amt = min_order_amount(ex, symbol)
    min_notional = min_amt * last if min_amt > 0 else 0.0
    base = (
        f"amount {amount} below exchange minimum {min_amt} for {symbol} "
        f"(≈{min_notional:.2f} USDT at mark {last:.4f}"
    )
    if notional_usdt is not None:
        base += f"; requested notional≈{notional_usdt:.2f} USDT"
    return base + ")"


def warn_if_max_notional_below_minimum(
    ex: ccxt.binanceusdm,
    settings: Settings,
    *,
    last: float | None = None,
    equity_usdt: float | None = None,
    available_margin_usdt: float | None = None,
) -> None:
    symbol = settings.symbol
    last_px = float(last) if last is not None else mark_last_usdt(ex, symbol)
    min_amt = min_order_amount(ex, symbol)
    if min_amt <= 0:
        return
    min_notional = min_amt * last_px
    if settings.max_notional_usdt + 1e-9 < min_notional:
        logger.warning(
            "MAX_NOTIONAL_USDT=%.2f is below the approximate minimum for %s "
            "(min amount %.8f × mark %.4f ≈ %.2f USDT). "
            "LONG/SHORT will be skipped until you raise the cap, deposit more margin, "
            "or switch SYMBOL (e.g. DOGE/USDT:USDT).",
            settings.max_notional_usdt,
            symbol,
            min_amt,
            last_px,
            min_notional,
        )
    sizing_base: float | None = None
    sizing_label = ""
    if settings.position_sizing == "equity_leverage" and equity_usdt is not None and equity_usdt > 0:
        sizing_base = float(equity_usdt)
        sizing_label = "wallet_total"
    elif (
        settings.position_sizing == "available_margin_leverage"
        and available_margin_usdt is not None
        and available_margin_usdt > 0
    ):
        sizing_base = float(available_margin_usdt)
        sizing_label = "available_margin"
    if sizing_base is not None:
        intent = sizing_base * settings.leverage * (settings.strategy_size_pct / 100.0)
        effective = min(intent, settings.max_notional_usdt)
        if effective + 1e-9 < min_notional:
            logger.warning(
                "POSITION_SIZING=%s would open ≈%.2f USDT (%s %.2f × leverage %.0f × "
                "STRATEGY_SIZE_PCT %.0f%%) but effective notional after MAX_NOTIONAL_USDT cap is %.2f, "
                "below min ≈%.2f USDT for %s — raise MAX_NOTIONAL_USDT or deposit more.",
                settings.position_sizing,
                intent,
                sizing_label,
                sizing_base,
                settings.leverage,
                settings.strategy_size_pct,
                effective,
                min_notional,
                symbol,
            )


def wait_for_legs(
    ex: ccxt.binanceusdm,
    symbol: str,
    settings: Settings,
    ok: Callable[[PositionLegs], bool],
) -> None:
    deadline = time.monotonic() + settings.position_poll_timeout_sec
    while time.monotonic() < deadline:
        if ok(fetch_position_legs(ex, symbol, dry_run=settings.dry_run)):
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
    last = mark_last_usdt(ex, symbol)
    if not amount_respects_limits(ex, symbol, amount, last=last):
        logger.warning(
            "ORDER skipped — %s",
            format_amount_limits_skip(ex, symbol, amount=amount, last=last),
        )
        return
    ex.create_order(symbol, "market", side, amount, params=params)
    if on_real_order is not None:
        on_real_order()
    if session is not None:
        session.record_executed_order()
