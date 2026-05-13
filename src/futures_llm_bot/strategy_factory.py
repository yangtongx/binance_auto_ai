"""Construct live rule strategies (same classes as backtest)."""

from __future__ import annotations

from pathlib import Path

from futures_llm_bot.backtest.engine import Strategy
from futures_llm_bot.backtest.strategies import (
    AtrBreakoutStrategy,
    BollingerBandCrossStrategy,
    FibonacciRetracementStrategy,
    IchimokuCloudStrategy,
    MacdCrossStrategy,
    RsiThresholdStrategy,
    SMACrossStrategy,
    StochasticCrossStrategy,
    VolumeProfileStrategy,
)
from futures_llm_bot.config import Settings
from futures_llm_bot.ml_signal_strategy import build_ml_strategy

_STRATEGY_NAMES = frozenset(
    {
        "sma_cross",
        "rsi",
        "macd",
        "bollinger",
        "bb",
        "ichimoku",
        "ichi",
        "fibonacci",
        "fib",
        "volume_profile",
        "vp",
        "stochastic",
        "stoch",
        "atr_breakout",
        "atr",
        "ml",
    }
)


def min_bars_for_backtest(
    name: str,
    *,
    slow: int = 30,
    rsi_period: int = 14,
    macd_signal: int = 9,
    bb_period: int = 20,
    senkou_b: int = 52,
    fib_lookback: int = 50,
    vp_bars: int = 48,
    ml_window: int = 32,
    stoch_k: int = 14,
    stoch_d: int = 3,
    atr_period: int = 14,
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
    if key in ("ichimoku", "ichi"):
        return senkou_b + 5
    if key in ("fibonacci", "fib"):
        return fib_lookback + 5
    if key in ("volume_profile", "vp"):
        return vp_bars + 5
    if key in ("stochastic", "stoch"):
        return stoch_k + stoch_d + 5
    if key in ("atr_breakout", "atr"):
        return atr_period + 5
    if key == "ml":
        return ml_window + 5
    return max(slow, bb_period, rsi_period) + 5


def strategy_min_ohlcv_bars(settings: Settings) -> int:
    """Minimum ``limit`` for ``fetch_ohlcv`` so strategy warmup is satisfied."""
    return min_bars_for_backtest(
        settings.strategy_name,
        slow=settings.strategy_slow,
        rsi_period=settings.strategy_rsi_period,
        macd_signal=settings.strategy_macd_signal,
        bb_period=settings.strategy_bb_period,
        senkou_b=settings.strategy_ichimoku_senkou_b,
        fib_lookback=settings.strategy_fib_lookback,
        vp_bars=settings.strategy_vp_bars,
        ml_window=settings.strategy_ml_window,
        stoch_k=settings.strategy_stoch_k,
        stoch_d=settings.strategy_stoch_d,
        atr_period=settings.strategy_atr_period,
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
    ichimoku_tenkan: int = 9,
    ichimoku_kijun: int = 26,
    ichimoku_senkou_b: int = 52,
    fib_lookback: int = 50,
    fib_level: str = "0.618",
    vp_bars: int = 48,
    vp_bins: int = 24,
    stoch_k: int = 14,
    stoch_d: int = 3,
    stoch_oversold: float = 20.0,
    stoch_overbought: float = 80.0,
    atr_period: int = 14,
    atr_mult: float = 1.5,
    ml_backend: str = "torch",
    ml_model_path: str | Path = "",
    ml_window: int = 32,
    ml_torch_arch: str = "mlp",
    ml_hot_reload: bool = False,
    ml_hot_reload_interval_sec: float = 30.0,
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
    if key in ("ichimoku", "ichi"):
        return IchimokuCloudStrategy(
            tenkan=ichimoku_tenkan,
            kijun=ichimoku_kijun,
            senkou_b=ichimoku_senkou_b,
            size_pct=size_pct,
            confidence=confidence,
        )
    if key in ("fibonacci", "fib"):
        return FibonacciRetracementStrategy(
            lookback=fib_lookback,
            level_key=fib_level,
            size_pct=size_pct,
            confidence=confidence,
        )
    if key in ("volume_profile", "vp"):
        return VolumeProfileStrategy(
            profile_bars=vp_bars,
            bins=vp_bins,
            size_pct=size_pct,
            confidence=confidence,
        )
    if key in ("stochastic", "stoch"):
        return StochasticCrossStrategy(
            k_period=stoch_k,
            d_period=stoch_d,
            oversold=stoch_oversold,
            overbought=stoch_overbought,
            size_pct=size_pct,
            confidence=confidence,
        )
    if key in ("atr_breakout", "atr"):
        return AtrBreakoutStrategy(
            atr_period=atr_period,
            mult=atr_mult,
            size_pct=size_pct,
            confidence=confidence,
        )
    if key == "ml":
        return build_ml_strategy(
            backend=ml_backend,
            model_path=ml_model_path,
            window=ml_window,
            size_pct=size_pct,
            confidence=confidence,
            torch_arch=ml_torch_arch,
            hot_reload=ml_hot_reload,
            hot_reload_interval_sec=ml_hot_reload_interval_sec,
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
        ichimoku_tenkan=settings.strategy_ichimoku_tenkan,
        ichimoku_kijun=settings.strategy_ichimoku_kijun,
        ichimoku_senkou_b=settings.strategy_ichimoku_senkou_b,
        fib_lookback=settings.strategy_fib_lookback,
        fib_level=settings.strategy_fib_level,
        vp_bars=settings.strategy_vp_bars,
        vp_bins=settings.strategy_vp_bins,
        stoch_k=settings.strategy_stoch_k,
        stoch_d=settings.strategy_stoch_d,
        stoch_oversold=settings.strategy_stoch_oversold,
        stoch_overbought=settings.strategy_stoch_overbought,
        atr_period=settings.strategy_atr_period,
        atr_mult=settings.strategy_atr_mult,
        ml_backend=settings.ml_backend,
        ml_model_path=settings.ml_model_path,
        ml_window=settings.strategy_ml_window,
        ml_torch_arch=settings.ml_torch_arch,
        ml_hot_reload=settings.ml_hot_reload,
        ml_hot_reload_interval_sec=settings.ml_hot_reload_interval_sec,
    )
