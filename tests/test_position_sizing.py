"""Tests for equity × leverage position sizing."""

from __future__ import annotations

from futures_llm_bot.config import Settings
from futures_llm_bot.execution_helpers import directional_notional_or_skip
from futures_llm_bot.schemas import Action, LLMSignal


def _sig(action: Action = Action.LONG, size_pct: float = 100.0) -> LLMSignal:
    return LLMSignal(action=action, size_pct=size_pct, confidence=0.9, reason="test")


def test_fixed_sizing_uses_max_notional() -> None:
    s = Settings.model_construct(
        position_sizing="fixed",
        max_notional_usdt=50.0,
        leverage=150.0,
    )
    assert directional_notional_or_skip(s, _sig(size_pct=50.0)) == 25.0


def test_equity_leverage_sizing() -> None:
    s = Settings.model_construct(
        position_sizing="equity_leverage",
        max_notional_usdt=10_000.0,
        leverage=150.0,
    )
    # 44 USDT × 150 × 100% = 6600
    assert directional_notional_or_skip(s, _sig(), equity_usdt=44.0) == 6600.0
    assert directional_notional_or_skip(s, _sig(size_pct=25.0), equity_usdt=80.0) == 3000.0


def test_equity_leverage_without_equity_returns_none() -> None:
    s = Settings.model_construct(position_sizing="equity_leverage", leverage=10.0, max_notional_usdt=100.0)
    assert directional_notional_or_skip(s, _sig(), equity_usdt=None) is None


def test_hold_returns_none() -> None:
    s = Settings.model_construct(position_sizing="equity_leverage", leverage=150.0, max_notional_usdt=100.0)
    assert directional_notional_or_skip(s, _sig(action=Action.HOLD), equity_usdt=44.0) is None


def test_available_margin_leverage_sizing() -> None:
    s = Settings.model_construct(
        position_sizing="available_margin_leverage",
        max_notional_usdt=10_000.0,
        leverage=150.0,
    )
    assert directional_notional_or_skip(s, _sig(), available_margin_usdt=40.0) == 6000.0
    assert directional_notional_or_skip(s, _sig(), equity_usdt=99.0, available_margin_usdt=None) is None


def test_available_margin_less_than_wallet() -> None:
    s = Settings.model_construct(
        position_sizing="available_margin_leverage",
        max_notional_usdt=10_000.0,
        leverage=10.0,
    )
    # 44 total but only 30 free (rest in positions)
    assert directional_notional_or_skip(s, _sig(), available_margin_usdt=30.0) == 300.0
