from __future__ import annotations

from unittest.mock import MagicMock, patch

from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.signal_probe import advice_from_action, evaluate_symbol_signal


def test_advice_mapping() -> None:
    assert advice_from_action(Action.LONG) == ("long", "做多")
    assert advice_from_action(Action.SHORT) == ("short", "做空")
    assert advice_from_action(Action.HOLD) == ("watch", "观望")
    assert advice_from_action(Action.FLAT) == ("watch", "观望")


def test_evaluate_symbol_signal_strategy() -> None:
    settings = MagicMock()
    settings.signal_source = "strategy"
    settings.min_confidence = 0.55
    settings.timeframe = "1m"
    settings.klines_limit = 100
    settings.strategy_name = "sma_cross"
    settings.model_copy.return_value = settings

    ex = MagicMock()
    ex.markets = {"DOGE/USDT:USDT": {"active": True, "linear": True}}
    sig = LLMSignal(action=Action.LONG, size_pct=25.0, confidence=0.8, reason="cross up")

    with (
        patch("futures_llm_bot.signal_probe.build_exchange", return_value=ex),
        patch("futures_llm_bot.signal_probe.load_binance_usdm_markets"),
        patch("futures_llm_bot.signal_probe.build_live_strategy") as bls,
        patch("futures_llm_bot.signal_probe.evaluate_candidate_signals", return_value={"DOGE/USDT:USDT": sig}),
        patch("futures_llm_bot.signal_probe.strategy_min_ohlcv_bars", return_value=50),
    ):
        bls.return_value = MagicMock()
        result = evaluate_symbol_signal(settings, "DOGE", ex=ex)

    assert result.ok is True
    assert result.symbol == "DOGE/USDT:USDT"
    assert result.advice == "long"
    assert result.advice_cn == "做多"
    assert result.would_trade is True
