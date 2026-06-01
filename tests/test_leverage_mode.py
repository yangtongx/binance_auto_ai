"""Tests for LEVERAGE_MODE=max (per-symbol max leverage) and equity-percent margin sizing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from binance_auto_ai import exchange_env
from binance_auto_ai.config import Settings
from binance_auto_ai.exchange_env import effective_leverage, symbol_max_leverage
from binance_auto_ai.execution_helpers import directional_notional_or_skip
from binance_auto_ai.schemas import Action, LLMSignal


class _LevEx:
    def __init__(self, *, market_max: float | None = None, tiers: dict | None = None) -> None:
        self._market_max = market_max
        self._tiers = tiers

    def market(self, symbol: str) -> dict:
        lev = {"max": self._market_max} if self._market_max is not None else {}
        return {"limits": {"leverage": lev}}

    def fetch_leverage_tiers(self, symbols: list[str]) -> dict:
        if self._tiers is None:
            raise RuntimeError("leverage tiers unavailable (no API)")
        return self._tiers


def _clear_cache() -> None:
    exchange_env._MAX_LEVERAGE_CACHE.clear()


def test_leverage_mode_validation() -> None:
    assert Settings.model_construct(leverage_mode="max").leverage_mode == "max"
    with pytest.raises(ValidationError, match="LEVERAGE_MODE"):
        Settings(leverage_mode="huge")


def test_symbol_max_leverage_from_market_limits() -> None:
    _clear_cache()
    ex = _LevEx(market_max=75.0)
    assert symbol_max_leverage(ex, "AAA/USDT:USDT") == 75.0  # type: ignore[arg-type]


def test_symbol_max_leverage_from_tiers_fallback() -> None:
    _clear_cache()
    ex = _LevEx(market_max=None, tiers={"BBB/USDT:USDT": [{"maxLeverage": 50}, {"maxLeverage": 20}]})
    assert symbol_max_leverage(ex, "BBB/USDT:USDT") == 50.0  # type: ignore[arg-type]


def test_symbol_max_leverage_unavailable_returns_none() -> None:
    _clear_cache()
    ex = _LevEx(market_max=None, tiers=None)
    assert symbol_max_leverage(ex, "CCC/USDT:USDT") is None  # type: ignore[arg-type]


def test_effective_leverage_max_mode_and_fallback() -> None:
    _clear_cache()
    s_max = Settings.model_construct(leverage_mode="max", leverage=20.0)
    ex = _LevEx(market_max=100.0)
    assert effective_leverage(ex, s_max, "DDD/USDT:USDT") == 100.0  # type: ignore[arg-type]

    _clear_cache()
    ex_none = _LevEx(market_max=None, tiers=None)
    # max unavailable -> fall back to LEVERAGE
    assert effective_leverage(ex_none, s_max, "EEE/USDT:USDT") == 20.0  # type: ignore[arg-type]


def test_effective_leverage_fixed_mode_ignores_exchange() -> None:
    _clear_cache()
    s_fixed = Settings.model_construct(leverage_mode="fixed", leverage=7.0)
    ex = _LevEx(market_max=125.0)
    assert effective_leverage(ex, s_fixed, "FFF/USDT:USDT") == 7.0  # type: ignore[arg-type]


def test_equity_leverage_margin_is_size_pct_of_equity() -> None:
    # margin = notional / leverage = equity * size_pct/100, independent of leverage
    sig = LLMSignal(action=Action.LONG, size_pct=5.0, confidence=0.9, reason="t")
    s = Settings.model_construct(position_sizing="equity_leverage", leverage=125.0)
    notional = directional_notional_or_skip(s, sig, equity_usdt=1000.0, available_margin_usdt=None)
    assert notional == pytest.approx(1000.0 * 125.0 * 0.05)  # 6250
    assert notional / 125.0 == pytest.approx(50.0)  # 5% of 1000
