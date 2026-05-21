"""In-memory runtime state for the trading dashboard (no database)."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from futures_llm_bot.config import Settings
from futures_llm_bot.time_display import utc_now_iso
from futures_llm_bot.schemas import LLMSignal
from futures_llm_bot.session_risk import SessionRisk

logger = logging.getLogger(__name__)

_MAX_DECISIONS = 40
_MAX_EVENTS = 80
# Keep up to 30 days of minute-level equity points (~43k entries, JSON ~2 MB).
_MAX_EQUITY_POINTS = 30 * 24 * 60
_HEALTH_EQUITY_POINTS = 240  # default chart payload (~4h at 1m)
_PERSIST_INTERVAL_SEC = 60.0

# Mapping from range key to lookback in seconds (None = all).
RANGE_SECONDS: dict[str, float | None] = {
    "5m": 300.0,
    "15m": 900.0,
    "1h": 3600.0,
    "6h": 21600.0,
    "1d": 86400.0,
    "1w": 604800.0,
    "1m": 2592000.0,
    "all": None,
}


def _parse_point_ts(t: str) -> float:
    try:
        return datetime.fromisoformat(t).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _signal_dict(signal: LLMSignal) -> dict[str, Any]:
    return signal.model_dump()


def _downsample(points: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if max_points <= 0 or len(points) <= max_points:
        return points
    step = len(points) / max_points
    out: list[dict[str, Any]] = []
    i = 0.0
    while int(i) < len(points) and len(out) < max_points:
        out.append(points[int(i)])
        i += step
    # Ensure the most recent point is preserved (chart end snaps to latest).
    if out and out[-1] is not points[-1]:
        out[-1] = points[-1]
    return out


class DashboardState:
    def __init__(self, persist_path: Path | None = None) -> None:
        self._lock = threading.Lock()
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
        self._persist_path: Path | None = persist_path
        self._last_persist_monotonic = 0.0
        if persist_path is not None:
            self._load_persisted()

    def set_persist_path(self, path: Path | None) -> None:
        with self._lock:
            self._persist_path = path
        if path is not None:
            self._load_persisted()

    def _load_persisted(self) -> None:
        path = self._persist_path
        if path is None or not path.is_file():
            return
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            points = data.get("equity_history") or []
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("equity history load failed (%s)", e)
            return
        with self._lock:
            for p in points[-_MAX_EQUITY_POINTS:]:
                if isinstance(p, dict) and "t" in p and "v" in p:
                    self._equity_history.append({"t": str(p["t"]), "v": float(p["v"])})
        logger.info("dashboard: loaded %d equity points from %s", len(self._equity_history), path)

    def _persist_throttled(self) -> None:
        path = self._persist_path
        if path is None:
            return
        now = time.monotonic()
        if now - self._last_persist_monotonic < _PERSIST_INTERVAL_SEC:
            return
        self._last_persist_monotonic = now
        snapshot = list(self._equity_history)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps({"equity_history": snapshot}), encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            logger.debug("equity history persist failed (%s)", e)

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
                    "at": utc_now_iso(),
                    "symbol": symbol,
                    "source": source,
                    "outcome": outcome,
                    "detail": detail,
                    "signal": _signal_dict(signal),
                }
            )

    def append_event(self, message: str) -> None:
        with self._lock:
            self._events.appendleft({"at": utc_now_iso(), "message": message[:500]})

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
            self._last_tick_at = utc_now_iso()
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
                # Always record one point per refresh so the chart has continuous
                # samples; we'll downsample for longer ranges on read.
                self._equity_history.append(
                    {"t": self._last_tick_at, "v": round(float(equity), 4)}
                )
                self._last_equity = float(equity)
            self._positions = positions
            self._session = session_stats
            self._persist_throttled()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = list(self._equity_history)[-_HEALTH_EQUITY_POINTS:]
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
                "equity_history": recent,
                "equity_history_total": len(self._equity_history),
                "last_tick_at": self._last_tick_at,
            }

    def equity_range(self, range_key: str, *, max_points: int = 600) -> dict[str, Any]:
        seconds = RANGE_SECONDS.get(range_key, RANGE_SECONDS["1h"])
        cutoff: float | None = None
        if seconds is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - seconds
        with self._lock:
            history = list(self._equity_history)
        if cutoff is not None:
            history = [p for p in history if _parse_point_ts(p["t"]) >= cutoff]
        sampled = _downsample(history, max_points)
        return {
            "range": range_key,
            "points": sampled,
            "raw_count": len(history),
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
    persist_path = _equity_history_path_for(settings)
    _state.set_persist_path(persist_path)
    _state.set_boot_config(settings, candidate_symbols=candidate_symbols)


def _equity_history_path_for(settings: Settings) -> Path:
    return Path(settings.state_file).parent / "equity_history.json"


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


def equity_range(range_key: str, *, max_points: int = 600) -> dict[str, Any]:
    return _state.equity_range(range_key, max_points=max_points)
