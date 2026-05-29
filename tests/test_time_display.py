from __future__ import annotations

from futures_llm_bot.time_display import format_iso_to_display


def test_format_iso_to_cst() -> None:
    # 2026-05-21 02:20:03 UTC -> 10:20:03 北京时间（同日）
    s = format_iso_to_display("2026-05-21T02:20:03.019163+00:00", compact=True)
    assert "05-21" in s
    assert "10:20:03" in s
