from __future__ import annotations

from binance_auto_ai.signal_reason_zh import reason_to_zh


def test_sma_cross_reasons() -> None:
    assert reason_to_zh("fast cross below") == "快线下穿慢线（死叉）"
    assert reason_to_zh("fast cross above") == "快线上穿慢线（金叉）"


def test_signal_pick_rotate() -> None:
    assert "换币" in reason_to_zh("signal_pick: rotate to PLAY/USDT:USDT")
    assert "PLAY/USDT" in reason_to_zh("signal_pick: rotate to PLAY/USDT:USDT")
