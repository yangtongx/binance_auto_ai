"""Pick one symbol from a whitelist by strongest rule-strategy signal (single position)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import ccxt

from futures_llm_bot.backtest.engine import Strategy
from futures_llm_bot.config import Settings
from futures_llm_bot.constants import NET_POSITION_EPS_CONTRACTS
from futures_llm_bot.positions import fetch_position_legs
from futures_llm_bot.risk_metrics import var_tail_block_reason_from_ohlcv
from futures_llm_bot.schemas import Action, LLMSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SymbolPick:
    symbol: str
    signal: LLMSignal
    score: float


@dataclass(frozen=True)
class TickTradeStep:
    symbol: str
    signal: LLMSignal


def parse_symbol_candidates(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _directional_score(signal: LLMSignal, *, min_confidence: float) -> float | None:
    if signal.action not in (Action.LONG, Action.SHORT):
        return None
    if signal.confidence < min_confidence:
        return None
    return float(signal.confidence)


def pick_best_directional(
    signals: dict[str, LLMSignal],
    *,
    candidates_order: list[str],
    min_confidence: float,
) -> SymbolPick | None:
    best: SymbolPick | None = None
    for sym in candidates_order:
        sig = signals.get(sym)
        if sig is None:
            continue
        score = _directional_score(sig, min_confidence=min_confidence)
        if score is None:
            continue
        if best is None or score > best.score or (score == best.score and sym < best.symbol):
            best = SymbolPick(sym, sig, score)
    return best


def find_open_position_symbol(
    ex: ccxt.binanceusdm,
    candidates: list[str],
    *,
    dry_run: bool,
) -> str | None:
    for sym in candidates:
        legs = fetch_position_legs(ex, sym, dry_run=dry_run)
        if abs(legs.signed_net()) >= NET_POSITION_EPS_CONTRACTS:
            return sym
    return None


def find_open_position_outside_candidates(
    ex: ccxt.binanceusdm,
    candidates: list[str],
    *,
    dry_run: bool,
) -> str | None:
    _ = dry_run
    candidate_set = set(candidates)
    try:
        rows = list(ex.fetch_positions())
    except ccxt.BaseError as e:
        logger.warning("fetch_positions (all) failed (%s); scanning whitelist only", e)
        return None
    for p in rows:
        sym = str(p.get("symbol") or "")
        if not sym or sym in candidate_set:
            continue
        c = float(p.get("contracts") or 0)
        if abs(c) >= NET_POSITION_EPS_CONTRACTS:
            return sym
    return None


def resolve_held_symbol(
    ex: ccxt.binanceusdm,
    candidates: list[str],
    *,
    dry_run: bool,
) -> tuple[str | None, bool]:
    """Return ``(symbol, in_whitelist)`` for the current open position, if any."""
    held = find_open_position_symbol(ex, candidates, dry_run=dry_run)
    if held is not None:
        return held, True
    outside = find_open_position_outside_candidates(ex, candidates, dry_run=dry_run)
    if outside is not None:
        return outside, False
    return None, True


def evaluate_candidate_signals(
    ex: ccxt.binanceusdm,
    settings: Settings,
    strategy: Strategy,
    candidates: list[str],
    *,
    ohlcv_limit: int,
) -> dict[str, LLMSignal]:
    signals: dict[str, LLMSignal] = {}
    for sym in candidates:
        ohlcv = ex.fetch_ohlcv(sym, timeframe=settings.timeframe, limit=ohlcv_limit)
        sig = strategy.on_bar(len(ohlcv) - 1, ohlcv)
        if (
            settings.risk_var_window > 0
            and settings.risk_var_block
            and sig.action in (Action.LONG, Action.SHORT)
        ):
            vmsg = var_tail_block_reason_from_ohlcv(
                ohlcv,
                window=settings.risk_var_window,
                alpha=settings.risk_var_alpha,
                tail_limit=settings.risk_var_tail_limit,
            )
            if vmsg:
                logger.info("signal_pick VaR blocked %s: %s", sym, vmsg)
                sig = LLMSignal(
                    action=Action.HOLD,
                    size_pct=0.0,
                    confidence=sig.confidence,
                    reason=f"var_blocked: {vmsg}",
                )
        signals[sym] = sig
    return signals


def _flat_signal(*, reason: str) -> LLMSignal:
    return LLMSignal(action=Action.FLAT, size_pct=0.0, confidence=1.0, reason=reason)


def plan_signal_pick_trades(
    signals: dict[str, LLMSignal],
    *,
    candidates: list[str],
    held_symbol: str | None,
    held_outside_whitelist: bool,
    min_confidence: float,
) -> list[TickTradeStep]:
    """
  Single-position policy:
  - Flat first if rotating or explicit FLAT on held symbol.
  - Open only the highest-confidence LONG/SHORT among candidates.
  """
    if held_outside_whitelist and held_symbol:
        return [TickTradeStep(held_symbol, _flat_signal(reason="signal_pick: flat non-whitelist position"))]

    best = pick_best_directional(signals, candidates_order=candidates, min_confidence=min_confidence)

    if held_symbol:
        held_sig = signals.get(
            held_symbol,
            LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=0.0, reason="missing bar"),
        )
        if held_sig.action == Action.FLAT:
            return [TickTradeStep(held_symbol, held_sig)]
        if best is not None and best.symbol != held_symbol:
            return [
                TickTradeStep(held_symbol, _flat_signal(reason=f"signal_pick: rotate to {best.symbol}")),
                TickTradeStep(best.symbol, best.signal),
            ]
        if best is not None and best.symbol == held_symbol:
            return [TickTradeStep(held_symbol, best.signal)]
        if held_sig.action in (Action.LONG, Action.SHORT) and _directional_score(
            held_sig, min_confidence=min_confidence
        ) is not None:
            return [TickTradeStep(held_symbol, held_sig)]
        return []

    if best is not None:
        return [TickTradeStep(best.symbol, best.signal)]
    return []


def log_candidate_signals(candidates: list[str], signals: dict[str, LLMSignal], *, pick: SymbolPick | None) -> None:
    parts: list[str] = []
    for sym in candidates:
        sig = signals.get(sym)
        if sig is None:
            parts.append(f"{sym}=?")
        else:
            parts.append(f"{sym}={sig.action.value}({sig.confidence:.2f})")
    pick_s = f"{pick.symbol} {pick.signal.action.value}" if pick else "none"
    logger.info("signal_pick scan: %s -> pick %s", ", ".join(parts), pick_s)
