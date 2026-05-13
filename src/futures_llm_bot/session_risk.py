from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from futures_llm_bot.config import Settings
from futures_llm_bot.schemas import Action

logger = logging.getLogger(__name__)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("state file unreadable (%s); starting fresh", e)
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


class SessionRisk:
    """Persisted per-day trade count and drawdown vs day-start USDT equity (UTC day).

    File updates are serialized with a `FileLock` so concurrent bot processes do not
    corrupt JSON; use a single instance per process.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = settings.state_file
        self._lock = FileLock(str(self._path.parent / (self._path.name + ".lock")), timeout=60)
        with self._lock:
            raw = _load(self._path)
            self._utc_date = raw.get("utc_date") or _today_utc()
            self._trade_count = int(raw.get("trade_count", 0))
            self._day_start_equity = raw.get("day_start_equity")
            if isinstance(self._day_start_equity, (int, float)):
                self._day_start_equity = float(self._day_start_equity)
            else:
                self._day_start_equity = None
            today = _today_utc()
            if today != self._utc_date:
                self._utc_date = today
                self._trade_count = 0
                self._day_start_equity = None
                _save(
                    self._path,
                    {
                        "utc_date": self._utc_date,
                        "trade_count": self._trade_count,
                        "day_start_equity": self._day_start_equity,
                    },
                )
                logger.info("session risk: rolled to new UTC day %s", self._utc_date)

    def on_tick(self, *, current_usdt_equity: float | None) -> None:
        with self._lock:
            if current_usdt_equity is None:
                return
            if self._day_start_equity is None:
                self._day_start_equity = float(current_usdt_equity)
                _save(
                    self._path,
                    {
                        "utc_date": self._utc_date,
                        "trade_count": self._trade_count,
                        "day_start_equity": self._day_start_equity,
                    },
                )
                logger.info("session risk: day_start_equity (UTC %s) = %.4f USDT", self._utc_date, self._day_start_equity)

    def drawdown_usdt(self, current_equity: float) -> float:
        with self._lock:
            if self._day_start_equity is None:
                return 0.0
            return max(0.0, float(self._day_start_equity) - float(current_equity))

    def warn_if_drawdown_near_limit(self, *, current_equity: float | None) -> None:
        """Log once per tick when drawdown crosses the configured warn ratio of the daily cap."""
        max_loss = self._settings.max_daily_loss_usdt
        ratio = self._settings.daily_loss_warn_ratio
        if max_loss <= 0 or current_equity is None or ratio <= 0:
            return
        with self._lock:
            if self._day_start_equity is None:
                return
            dd = max(0.0, float(self._day_start_equity) - float(current_equity))
        if dd >= max_loss * ratio:
            logger.warning(
                "session risk: drawdown %.4f USDT (%.0f%% of max_daily_loss_usdt=%.4f)",
                dd,
                100.0 * dd / max_loss if max_loss else 0.0,
                max_loss,
            )

    def block_reason_for(self, signal_action: Action, *, current_equity: float | None) -> str | None:
        with self._lock:
            if signal_action in (Action.HOLD, Action.FLAT):
                return None
            max_trades = self._settings.max_trades_per_day
            if max_trades > 0 and self._trade_count >= max_trades:
                return f"max_trades_per_day reached ({self._trade_count}/{max_trades})"

            max_loss = self._settings.max_daily_loss_usdt
            if max_loss > 0:
                if current_equity is None:
                    return "max_daily_loss_usdt is set but futures USDT equity could not be read"
                if self._day_start_equity is not None:
                    dd = max(0.0, float(self._day_start_equity) - float(current_equity))
                    if dd >= max_loss:
                        return f"max_daily_loss_usdt exceeded (drawdown≈{dd:.2f} >= {max_loss})"
            return None

    def record_executed_order(self) -> None:
        with self._lock:
            self._trade_count += 1
            _save(
                self._path,
                {
                    "utc_date": self._utc_date,
                    "trade_count": self._trade_count,
                    "day_start_equity": self._day_start_equity,
                },
            )
            logger.info("session risk: trade_count=%s (UTC %s)", self._trade_count, self._utc_date)
