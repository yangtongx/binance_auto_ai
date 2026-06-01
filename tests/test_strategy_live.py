from __future__ import annotations

import pytest
from pydantic import ValidationError

from binance_auto_ai.config import Settings
from binance_auto_ai.strategy_factory import build_live_strategy


def test_settings_strategy_requires_fast_lt_slow() -> None:
    with pytest.raises(ValidationError, match="STRATEGY_FAST"):
        Settings(
            signal_source="strategy",
            strategy_fast=30,
            strategy_slow=30,
        )


def test_unknown_strategy_name_rejected() -> None:
    with pytest.raises(ValidationError, match="STRATEGY_NAME"):
        Settings(signal_source="strategy", strategy_name="unknown_xyz")


def test_build_live_strategy_on_bar_no_llm() -> None:
    settings = Settings(
        signal_source="strategy",
        strategy_name="sma_cross",
        strategy_fast=2,
        strategy_slow=3,
        strategy_size_pct=100.0,
        strategy_confidence=0.9,
    )
    strat = build_live_strategy(settings)
    # 5 根 K：预热需 slow+1=4 根收盘，前一根用于金叉逻辑
    ohlcv = [
        [1, 10, 10, 10, 10, 1],
        [2, 10, 10, 10, 11, 1],
        [3, 11, 11, 11, 12, 1],
        [4, 12, 12, 12, 13, 1],
        [5, 13, 13, 13, 20, 1],
    ]
    sig = strat.on_bar(len(ohlcv) - 1, ohlcv)
    assert sig.confidence == pytest.approx(0.9)
    assert sig.action.value in ("long", "short", "hold", "flat")


def test_ml_tensorflow_disallows_sequence_arch() -> None:
    with pytest.raises(ValidationError, match="ML_TORCH_ARCH"):
        Settings(
            signal_source="strategy",
            strategy_name="ml",
            ml_backend="tf",
            ml_model_path="dummy.keras",
            ml_torch_arch="lstm",
        )
