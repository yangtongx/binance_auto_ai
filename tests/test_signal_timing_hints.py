from __future__ import annotations

from unittest.mock import MagicMock

from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.signal_timing_hints import build_watch_timing_hints


def _ohlcv_from_closes(closes: list[float]) -> list[list[float]]:
    rows: list[list[float]] = []
    for i, c in enumerate(closes):
        rows.append([float(i * 60_000), c, c * 1.001, c * 0.999, c, 1000.0])
    return rows


def test_sma_cross_hold_gives_long_and_short_hints() -> None:
    # Down-then-flat series: fast SMA below slow → hold, with actionable hints.
    n = 60
    closes = [100.0 - i * 0.3 for i in range(n - 10)] + [70.0] * 10
    ohlcv = _ohlcv_from_closes(closes)
    settings = MagicMock()
    settings.signal_source = "strategy"
    settings.strategy_name = "sma_cross"
    settings.strategy_fast = 10
    settings.strategy_slow = 30
    settings.timeframe = "1m"
    signal = LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=0.8, reason="no cross")

    hints = build_watch_timing_hints(ohlcv, settings, signal)
    assert len(hints) == 2
    assert hints[0].side == "long"
    assert hints[1].side == "short"
    assert hints[0].levels
    assert any("高点" in lv.label for lv in hints[0].levels)
    assert "触发价位" in hints[0].trigger
    d = hints[0].to_dict()
    assert d["levels"][0]["price_fmt"]


def test_hold_only() -> None:
    hints = build_watch_timing_hints([], MagicMock(), LLMSignal(action=Action.LONG, size_pct=1, confidence=1))
    assert hints == []
