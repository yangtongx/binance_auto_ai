from __future__ import annotations

from futures_llm_bot.observability import _DASHBOARD_HTML


def test_dashboard_page_embeds_health_poll() -> None:
    assert "/health" in _DASHBOARD_HTML
    assert "equity-chart" in _DASHBOARD_HTML
    assert "/api/status" in _DASHBOARD_HTML
    assert "/api/equity" in _DASHBOARD_HTML
    assert "range-btn" in _DASHBOARD_HTML
    assert "/metrics" in _DASHBOARD_HTML
