"""Tests for whitelist signal_pick planning."""

from __future__ import annotations

from binance_auto_ai.schemas import Action, LLMSignal
from binance_auto_ai.symbol_picker import (
    pick_best_directional,
    plan_signal_pick_trades,
)


def _sig(action: Action, confidence: float = 0.9) -> LLMSignal:
    return LLMSignal(action=action, size_pct=100.0, confidence=confidence, reason="t")


def test_pick_best_by_confidence() -> None:
    cands = ["A/USDT:USDT", "B/USDT:USDT"]
    signals = {
        "A/USDT:USDT": _sig(Action.LONG, 0.7),
        "B/USDT:USDT": _sig(Action.SHORT, 0.85),
    }
    pick = pick_best_directional(signals, candidates_order=cands, min_confidence=0.55)
    assert pick is not None
    assert pick.symbol == "B/USDT:USDT"


def test_plan_open_best_when_flat() -> None:
    cands = ["A/USDT:USDT", "B/USDT:USDT"]
    signals = {
        "A/USDT:USDT": _sig(Action.HOLD, 0.9),
        "B/USDT:USDT": _sig(Action.LONG, 0.8),
    }
    steps = plan_signal_pick_trades(
        signals, candidates=cands, held_symbol=None, held_outside_whitelist=False, min_confidence=0.55
    )
    assert len(steps) == 1
    assert steps[0].symbol == "B/USDT:USDT"
    assert steps[0].signal.action == Action.LONG


def test_plan_rotate_position() -> None:
    cands = ["A/USDT:USDT", "B/USDT:USDT"]
    signals = {
        "A/USDT:USDT": _sig(Action.HOLD, 0.9),
        "B/USDT:USDT": _sig(Action.LONG, 0.9),
    }
    steps = plan_signal_pick_trades(
        signals,
        candidates=cands,
        held_symbol="A/USDT:USDT",
        held_outside_whitelist=False,
        min_confidence=0.55,
    )
    assert len(steps) == 2
    assert steps[0].symbol == "A/USDT:USDT"
    assert steps[0].signal.action == Action.FLAT
    assert steps[1].symbol == "B/USDT:USDT"


def test_plan_hold_keeps_position() -> None:
    cands = ["A/USDT:USDT", "B/USDT:USDT"]
    signals = {
        "A/USDT:USDT": _sig(Action.HOLD, 0.9),
        "B/USDT:USDT": _sig(Action.HOLD, 0.9),
    }
    steps = plan_signal_pick_trades(
        signals,
        candidates=cands,
        held_symbol="A/USDT:USDT",
        held_outside_whitelist=False,
        min_confidence=0.55,
    )
    assert steps == []


def test_hysteresis_keeps_held_when_new_only_marginally_stronger() -> None:
    cands = ["A/USDT:USDT", "B/USDT:USDT"]
    signals = {
        "A/USDT:USDT": _sig(Action.LONG, 0.70),
        "B/USDT:USDT": _sig(Action.LONG, 0.72),
    }
    steps = plan_signal_pick_trades(
        signals,
        candidates=cands,
        held_symbol="A/USDT:USDT",
        held_outside_whitelist=False,
        min_confidence=0.55,
        rotation_hysteresis=0.05,
    )
    # 0.72 < 0.70 + 0.05 → 不换币，继续持 A
    assert len(steps) == 1
    assert steps[0].symbol == "A/USDT:USDT"
    assert steps[0].signal.action == Action.LONG


def test_hysteresis_rotates_when_new_clearly_stronger() -> None:
    cands = ["A/USDT:USDT", "B/USDT:USDT"]
    signals = {
        "A/USDT:USDT": _sig(Action.LONG, 0.70),
        "B/USDT:USDT": _sig(Action.LONG, 0.80),
    }
    steps = plan_signal_pick_trades(
        signals,
        candidates=cands,
        held_symbol="A/USDT:USDT",
        held_outside_whitelist=False,
        min_confidence=0.55,
        rotation_hysteresis=0.05,
    )
    # 0.80 >= 0.70 + 0.05 → 平 A 换 B
    assert len(steps) == 2
    assert steps[0].symbol == "A/USDT:USDT"
    assert steps[0].signal.action == Action.FLAT
    assert steps[1].symbol == "B/USDT:USDT"


def test_hysteresis_rotates_when_held_no_longer_directional() -> None:
    cands = ["A/USDT:USDT", "B/USDT:USDT"]
    signals = {
        "A/USDT:USDT": _sig(Action.HOLD, 0.99),
        "B/USDT:USDT": _sig(Action.LONG, 0.60),
    }
    steps = plan_signal_pick_trades(
        signals,
        candidates=cands,
        held_symbol="A/USDT:USDT",
        held_outside_whitelist=False,
        min_confidence=0.55,
        rotation_hysteresis=0.5,
    )
    # 在手已是 hold（非有效方向）→ 迟滞不生效，直接换到最优 B
    assert len(steps) == 2
    assert steps[0].signal.action == Action.FLAT
    assert steps[1].symbol == "B/USDT:USDT"
