from __future__ import annotations

from futures_llm_bot.observability import _DASHBOARD_HTML


def test_dashboard_page_embeds_health_poll() -> None:
    assert "/health" in _DASHBOARD_HTML
    assert "ticks-att" in _DASHBOARD_HTML
    assert "/metrics" in _DASHBOARD_HTML
