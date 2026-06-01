"""进程内指标：tick 计数、LLM 调用、/health 与 Prometheus /metrics 文本。"""

from __future__ import annotations

import threading
import time
from typing import Any

from binance_auto_ai import __version__
from binance_auto_ai import dashboard_state

_lock = threading.Lock()
_started = time.time()
_ticks_attempted = 0
_ticks_failed = 0
_ticks_risk_blocked = 0
_ticks_completed = 0
_real_orders = 0
_llm_calls = 0
_llm_failures = 0
_llm_duration_sec_total = 0.0
_last_tick_monotonic: float | None = None
_last_error: str | None = None


def record_tick_attempt() -> None:
    global _ticks_attempted, _last_tick_monotonic
    with _lock:
        _ticks_attempted += 1
        _last_tick_monotonic = time.monotonic()


def record_tick_completed() -> None:
    global _ticks_completed
    with _lock:
        _ticks_completed += 1


def record_tick_failed(message: str | None = None) -> None:
    global _ticks_failed, _last_error
    with _lock:
        _ticks_failed += 1
        if message:
            _last_error = message[:2000]


def record_tick_risk_blocked() -> None:
    global _ticks_risk_blocked
    with _lock:
        _ticks_risk_blocked += 1


def record_real_order() -> None:
    global _real_orders
    with _lock:
        _real_orders += 1


def record_llm_success(duration_sec: float) -> None:
    global _llm_calls, _llm_duration_sec_total
    with _lock:
        _llm_calls += 1
        _llm_duration_sec_total += max(0.0, duration_sec)


def record_llm_failure() -> None:
    global _llm_failures
    with _lock:
        _llm_failures += 1


def snapshot() -> dict[str, Any]:
    with _lock:
        avg_llm_ms = 0.0
        if _llm_calls > 0:
            avg_llm_ms = (_llm_duration_sec_total / _llm_calls) * 1000.0
        return {
            "status": "healthy" if _ticks_failed == 0 else "degraded",
            "version": __version__,
            "uptime_s": round(time.time() - _started, 3),
            "ticks": {
                "attempted": _ticks_attempted,
                "completed": _ticks_completed,
                "failed": _ticks_failed,
                "risk_or_session_blocked": _ticks_risk_blocked,
            },
            "orders": {"real_submitted": _real_orders},
            "llm": {
                "calls": _llm_calls,
                "failures": _llm_failures,
                "avg_duration_ms": round(avg_llm_ms, 2),
            },
            "last_error": _last_error,
            "dashboard": dashboard_state.snapshot(),
        }


def prometheus_text() -> str:
    with _lock:
        lines = [
            "# HELP binance_auto_ai_ticks_attempted Total tick attempts",
            "# TYPE binance_auto_ai_ticks_attempted counter",
            f"binance_auto_ai_ticks_attempted {_ticks_attempted}",
            "# HELP binance_auto_ai_ticks_failed Ticks that raised an exception",
            "# TYPE binance_auto_ai_ticks_failed counter",
            f"binance_auto_ai_ticks_failed {_ticks_failed}",
            "# HELP binance_auto_ai_ticks_risk_blocked Ticks blocked by risk/session before trading",
            "# TYPE binance_auto_ai_ticks_risk_blocked counter",
            f"binance_auto_ai_ticks_risk_blocked {_ticks_risk_blocked}",
            "# HELP binance_auto_ai_real_orders_submitted Non-test orders sent to the exchange",
            "# TYPE binance_auto_ai_real_orders_submitted counter",
            f"binance_auto_ai_real_orders_submitted {_real_orders}",
            "# HELP binance_auto_ai_llm_calls Successful LLM round-trips",
            "# TYPE binance_auto_ai_llm_calls counter",
            f"binance_auto_ai_llm_calls {_llm_calls}",
            "# HELP binance_auto_ai_llm_failures LLM errors after retries",
            "# TYPE binance_auto_ai_llm_failures counter",
            f"binance_auto_ai_llm_failures {_llm_failures}",
        ]
    return "\n".join(lines) + "\n"
