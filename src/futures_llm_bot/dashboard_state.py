"""In-memory runtime state for the trading dashboard (no database)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from futures_llm_bot.config import Settings
from futures_llm_bot.schemas import LLMSignal
from futures_llm_bot.session_risk import SessionRisk

_MAX_DECISIONS = 40
_MAX_EVENTS = 80
_MAX_EQUITY_POINTS = 480


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _signal_dict(signal: LLMSignal) -> dict[str, Any]:
    return signal.model_dump()


class DashboardState:
    def __init__(self) -> None:
        self._lock = __import__("threading").Lock()
        self._config: dict[str, Any] = {}
        self._account: dict[str, Any] = {}
        self._positions: list[dict[str, Any]] = []
        self._session: dict[str, Any] = {}
        self._candidates: list[str] = []
        self._signals: dict[str, dict[str, Any]] = {}
        self._pick: dict[str, Any] | None = None
        self._decisions: deque[dict[str, Any]] = deque(maxlen=_MAX_DECISIONS)
        self._events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
        self._equity_history: deque[dict[str, Any]] = deque(maxlen=_MAX_EQUITY_POINTS)
        self._last_tick_at: str | None = None
        self._last_equity: float | None = None

    def set_boot_config(
        self,
        settings: Settings,
        *,
        candidate_symbols: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._config = {
                "symbol": settings.symbol,
                "symbol_mode": settings.symbol_mode,
                "signal_source": settings.signal_source,
                "strategy_name": settings.strategy_name,
                "timeframe": settings.timeframe,
                "dry_run": settings.dry_run,
                "binance_testnet": settings.binance_testnet,
                "position_sizing": settings.position_sizing,
                "leverage": settings.leverage,
                "max_notional_usdt": settings.max_notional_usdt,
                "min_confidence": settings.min_confidence,
                "symbol_candidates": settings.symbol_candidates,
            }
            if candidate_symbols is not None:
                self._candidates = list(candidate_symbols)

    def set_candidates(self, symbols: list[str], *, pick: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._candidates = list(symbols)
            self._pick = pick

    def set_signals(self, signals: dict[str, LLMSignal]) -> None:
        with self._lock:
            self._signals = {sym: _signal_dict(sig) for sym, sig in signals.items()}

    def note_pick(self, *, symbol: str, signal: LLMSignal, score: float) -> None:
        with self._lock:
            self._pick = {"symbol": symbol, "signal": _signal_dict(signal), "score": score}

    def append_decision(
        self,
        *,
        symbol: str,
        signal: LLMSignal,
        source: str,
        outcome: str,
        detail: str = "",
    ) -> None:
        with self._lock:
            self._decisions.appendleft(
                {
                    "at": _utc_now(),
                    "symbol": symbol,
                    "source": source,
                    "outcome": outcome,
                    "detail": detail,
                    "signal": _signal_dict(signal),
                }
            )

    def append_event(self, message: str) -> None:
        with self._lock:
            self._events.appendleft({"at": _utc_now(), "message": message[:500]})

    def refresh_exchange(
        self,
        ex: Any,
        settings: Settings,
        session: SessionRisk,
    ) -> None:
        from futures_llm_bot.positions import fetch_futures_usdt_balance

        equity, available = fetch_futures_usdt_balance(ex)
        positions = _fetch_open_positions(ex, dry_run=settings.dry_run)
        unrealized = sum(float(p.get("unrealized_pnl") or 0) for p in positions)
        session_stats = session.snapshot_stats(current_equity=equity)

        with self._lock:
            self._last_tick_at = _utc_now()
            self._account = {
                "equity_usdt": equity,
                "available_margin_usdt": available,
                "unrealized_pnl_usdt": round(unrealized, 4) if positions else None,
                "updated_at": self._last_tick_at,
            }
            if equity is not None:
                day_start = session_stats.get("day_start_equity")
                if isinstance(day_start, (int, float)) and day_start > 0:
                    self._account["day_pnl_usdt"] = round(float(equity) - float(day_start), 4)
                    self._account["day_pnl_pct"] = round(
                        (float(equity) - float(day_start)) / float(day_start) * 100.0, 3
                    )
                if self._last_equity is None or abs(float(equity) - self._last_equity) > 1e-6:
                    self._equity_history.append({"t": self._last_tick_at, "v": round(float(equity), 4)})
                    self._last_equity = float(equity)
            self._positions = positions
            self._session = session_stats

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "config": dict(self._config),
                "account": dict(self._account),
                "session": dict(self._session),
                "positions": list(self._positions),
                "candidates": list(self._candidates),
                "signals": dict(self._signals),
                "pick": self._pick,
                "decisions": list(self._decisions),
                "events": list(self._events),
                "equity_history": list(self._equity_history),
                "last_tick_at": self._last_tick_at,
            }


def _fetch_open_positions(ex: Any, *, dry_run: bool) -> list[dict[str, Any]]:
    try:
        rows = list(ex.fetch_positions())
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for p in rows:
        try:
            contracts = float(p.get("contracts") or 0)
        except (TypeError, ValueError):
            contracts = 0.0
        if abs(contracts) < 1e-12:
            continue
        upnl = p.get("unrealizedPnl")
        try:
            upnl_f = float(upnl) if upnl is not None else None
        except (TypeError, ValueError):
            upnl_f = None
        out.append(
            {
                "symbol": p.get("symbol"),
                "side": p.get("side"),
                "contracts": contracts,
                "notional": p.get("notional"),
                "entry_price": p.get("entryPrice"),
                "mark_price": p.get("markPrice"),
                "leverage": p.get("leverage"),
                "unrealized_pnl": upnl_f,
            }
        )
    return out


_state = DashboardState()


def set_boot_config(settings: Settings, *, candidate_symbols: list[str] | None = None) -> None:
    _state.set_boot_config(settings, candidate_symbols=candidate_symbols)


def set_candidates(symbols: list[str], *, pick: dict[str, Any] | None = None) -> None:
    _state.set_candidates(symbols, pick=pick)


def set_signals(signals: dict[str, LLMSignal]) -> None:
    _state.set_signals(signals)


def note_pick(*, symbol: str, signal: LLMSignal, score: float) -> None:
    _state.note_pick(symbol=symbol, signal=signal, score=score)


def append_decision(
    *,
    symbol: str,
    signal: LLMSignal,
    source: str,
    outcome: str,
    detail: str = "",
) -> None:
    _state.append_decision(symbol=symbol, signal=signal, source=source, outcome=outcome, detail=detail)


def append_event(message: str) -> None:
    _state.append_event(message)


def refresh_exchange(ex: Any, settings: Settings, session: SessionRisk) -> None:
    _state.refresh_exchange(ex, settings, session)


def snapshot() -> dict[str, Any]:
    return _state.snapshot()
