from __future__ import annotations

from futures_llm_bot import metrics


def test_metrics_snapshot_has_status() -> None:
    metrics.record_tick_attempt()
    metrics.record_tick_completed()
    snap = metrics.snapshot()
    assert snap["status"] in ("healthy", "degraded")
    assert "ticks" in snap
    assert "llm" in snap
    pt = metrics.prometheus_text()
    assert "futures_llm_bot_ticks_attempted" in pt
