"""Construct live rule strategies (same classes as backtest)."""

from __future__ import annotations

from futures_llm_bot.backtest.engine import Strategy
from futures_llm_bot.backtest.strategies import (
    BollingerBandCrossStrategy,
    MacdCrossStrategy,
    RsiThresholdStrategy,
    SMACrossStrategy,
)
from futures_llm_bot.config import Settings

_STRATEGY_NAMES = frozenset({"sma_cross", "rsi", "macd", "bollinger", "bb"})


def min_bars_for_backtest(
    name: str,
    *,
    slow: int = 30,
    rsi_period: int = 14,
    macd_signal: int = 9,
    bb_period: int = 20,
) -> int:
    """Minimum OHLCV length for warmup (matches live ``strategy_min_ohlcv_bars`` logic)."""
    key = name.strip().lower()
    if key == "sma_cross":
        return slow + 5
    if key == "rsi":
        return rsi_period + 5
    if key == "macd":
        return slow + macd_signal + 10
    if key in ("bollinger", "bb"):
        return bb_period + 5
    return max(slow, bb_period, rsi_period) + 5


def strategy_min_ohlcv_bars(settings: Settings) -> int:
    """Minimum ``limit`` for ``fetch_ohlcv`` so strategy warmup is satisfied."""
    return min_bars_for_backtest(
        settings.strategy_name,
        slow=settings.strategy_slow,
        rsi_period=settings.strategy_rsi_period,
        macd_signal=settings.strategy_macd_signal,
        bb_period=settings.strategy_bb_period,
    )


def build_strategy_for_backtest(
    name: str,
    *,
    fast: int,
    slow: int,
    size_pct: float = 100.0,
    confidence: float = 0.8,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
    macd_signal: int = 9,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> Strategy:
    key = name.strip().lower()
    if key == "sma_cross":
        return SMACrossStrategy(fast=fast, slow=slow, size_pct=size_pct, confidence=confidence)
    if key == "rsi":
        return RsiThresholdStrategy(
            period=rsi_period,
            oversold=rsi_oversold,
            overbought=rsi_overbought,
            size_pct=size_pct,
            confidence=confidence,
        )
    if key == "macd":
        return MacdCrossStrategy(
            fast=fast,
            slow=slow,
            signal_period=macd_signal,
            size_pct=size_pct,
            confidence=confidence,
        )
    if key in ("bollinger", "bb"):
        return BollingerBandCrossStrategy(
            period=bb_period,
            num_std=bb_std,
            size_pct=size_pct,
            confidence=confidence,
        )
    allowed = ", ".join(sorted(_STRATEGY_NAMES))
    raise ValueError(f"Unknown strategy {name!r} (supported: {allowed})")


def build_live_strategy(settings: Settings) -> Strategy:
    """Return a strategy implementing ``reset`` / ``on_bar`` → ``LLMSignal``."""
    return build_strategy_for_backtest(
        settings.strategy_name,
        fast=settings.strategy_fast,
        slow=settings.strategy_slow,
        size_pct=settings.strategy_size_pct,
        confidence=settings.strategy_confidence,
        rsi_period=settings.strategy_rsi_period,
        rsi_oversold=settings.strategy_rsi_oversold,
        rsi_overbought=settings.strategy_rsi_overbought,
        macd_signal=settings.strategy_macd_signal,
        bb_period=settings.strategy_bb_period,
        bb_std=settings.strategy_bb_std,
    )
