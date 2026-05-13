"""Example deterministic strategies (rule-based, reproducible)."""

from __future__ import annotations

import numpy as np

from futures_llm_bot.backtest.indicators import (
    BollingerStream,
    MACDStream,
    RSIWilderStream,
    SMACrossStream,
    atr_wilder_series,
    ema_series,
    fibonacci_retracement_levels,
    ichimoku_signal_state,
    rsi_wilder_series,
    stochastic_cross_state,
    volume_profile_poc,
)
from futures_llm_bot.risk_metrics import rolling_median_realized_vol
from futures_llm_bot.schemas import Action, LLMSignal


def _closes_list(ohlcv: list[list[float]]) -> list[float]:
    return [float(bar[4]) for bar in ohlcv]


def _rsi_series_compat(closes: list[float], period: int) -> list[float | None]:
    """Lists with ``None`` where undefined (tests / callers expecting old shape)."""
    arr = rsi_wilder_series(np.asarray(closes, dtype=np.float64), period)
    out: list[float | None] = []
    for x in arr:
        out.append(None if np.isnan(x) else float(x))
    return out


class SMACrossStrategy:
    """Fast SMA crosses above slow → long; cross below → short; else hold."""

    def __init__(self, fast: int = 10, slow: int = 30, *, size_pct: float = 100.0, confidence: float = 0.8) -> None:
        if fast >= slow:
            raise ValueError("fast period must be < slow period")
        self._size_pct = size_pct
        self._confidence = confidence
        self._stream = SMACrossStream(fast, slow)

    def reset(self) -> None:
        self._stream.reset()

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        self._stream.ensure(_closes_list(ohlcv))
        x = self._stream.cross()
        if x is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        f_prev, s_prev, f_now, s_now = x
        if f_prev <= s_prev and f_now > s_now:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="fast cross above",
            )
        if f_prev >= s_prev and f_now < s_now:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="fast cross below",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="no cross")


class RsiThresholdStrategy:
    """Mean reversion: RSI below oversold → long; above overbought → short; else hold."""

    def __init__(
        self,
        period: int = 14,
        *,
        oversold: float = 30.0,
        overbought: float = 70.0,
        size_pct: float = 100.0,
        confidence: float = 0.8,
    ) -> None:
        if period < 2:
            raise ValueError("RSI period must be >= 2")
        if not 0.0 < oversold < overbought < 100.0:
            raise ValueError("need 0 < oversold < overbought < 100")
        self._os = oversold
        self._ob = overbought
        self._size_pct = size_pct
        self._confidence = confidence
        self._stream = RSIWilderStream(period)

    def reset(self) -> None:
        self._stream.reset()

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        self._stream.ensure(_closes_list(ohlcv))
        rsi = self._stream.rsi()
        if rsi is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        if rsi < self._os:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason=f"rsi<{self._os:.0f}",
            )
        if rsi > self._ob:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason=f"rsi>{self._ob:.0f}",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="rsi mid")


class RsiVolAdaptiveStrategy:
    """RSI mean-reversion with **oversold/overbought bands** widened or tightened from realized vol."""

    def __init__(
        self,
        period: int = 14,
        *,
        oversold: float = 30.0,
        overbought: float = 70.0,
        vol_window: int = 20,
        vol_ref_window: int = 100,
        vol_sensitivity: float = 10.0,
        size_pct: float = 100.0,
        confidence: float = 0.8,
    ) -> None:
        if period < 2:
            raise ValueError("RSI period must be >= 2")
        if not 0.0 < oversold < overbought < 100.0:
            raise ValueError("need 0 < oversold < overbought < 100")
        if vol_window < 3 or vol_ref_window < 5:
            raise ValueError("vol windows too small")
        if vol_sensitivity <= 0:
            raise ValueError("vol_sensitivity must be > 0")
        self._base_os = oversold
        self._base_ob = overbought
        self._vw = vol_window
        self._rw = vol_ref_window
        self._sens = vol_sensitivity
        self._size_pct = size_pct
        self._confidence = confidence
        self._stream = RSIWilderStream(period)

    def reset(self) -> None:
        self._stream.reset()

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        closes = _closes_list(ohlcv)
        self._stream.ensure(closes)
        rsi = self._stream.rsi()
        cur_s, ref_s = rolling_median_realized_vol(closes, vol_window=self._vw, ref_window=self._rw)
        if rsi is None or cur_s != cur_s or ref_s != ref_s:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="rsi_vol:warmup")
        factor = cur_s / (ref_s + 1e-12)
        factor = float(np.clip(factor, 0.5, 2.0))
        adj = (factor - 1.0) * self._sens
        os_eff = float(np.clip(self._base_os + adj, 10.0, 48.0))
        ob_eff = float(np.clip(self._base_ob - adj, 52.0, 90.0))
        if not (os_eff + 1.0 < ob_eff):
            os_eff, ob_eff = self._base_os, self._base_ob
        if rsi < os_eff:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason=f"rsi<{os_eff:.1f}(vol)",
            )
        if rsi > ob_eff:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason=f"rsi>{ob_eff:.1f}(vol)",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="rsi mid(vol)")


class MacdCrossStrategy:
    """MACD line crosses above signal → long; cross below → short."""

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_period: int = 9,
        *,
        size_pct: float = 100.0,
        confidence: float = 0.8,
    ) -> None:
        if fast >= slow:
            raise ValueError("MACD fast EMA span must be < slow span")
        if signal_period < 1:
            raise ValueError("MACD signal period must be >= 1")
        self._size_pct = size_pct
        self._confidence = confidence
        self._stream = MACDStream(fast, slow, signal_period)

    def reset(self) -> None:
        self._stream.reset()

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        c = _closes_list(ohlcv)
        self._stream.ensure(c)
        x = self._stream.cross()
        if x is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        mp, sp, mn, sn = x
        if mp <= sp and mn > sn:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="macd cross up",
            )
        if mp >= sp and mn < sn:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="macd cross down",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="macd no cross")


class BollingerBandCrossStrategy:
    """Price crosses **below** lower band → long; crosses **above** upper → short (mean reversion style)."""

    def __init__(
        self,
        period: int = 20,
        num_std: float = 2.0,
        *,
        size_pct: float = 100.0,
        confidence: float = 0.8,
    ) -> None:
        if period < 3:
            raise ValueError("Bollinger period must be >= 3")
        if num_std <= 0:
            raise ValueError("num_std must be > 0")
        self._size_pct = size_pct
        self._confidence = confidence
        self._stream = BollingerStream(period, num_std)

    def reset(self) -> None:
        self._stream.reset()

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        self._stream.ensure(_closes_list(ohlcv))
        got = self._stream.cross_bounds()
        if got is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        prev_c, now_c, u_prev, l_prev, u_now, l_now = got
        if prev_c >= l_prev and now_c < l_now:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="bb cross below lower",
            )
        if prev_c <= u_prev and now_c > u_now:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="bb cross above upper",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="bb inside")


class IchimokuCloudStrategy:
    """Tenkan/Kijun cross with cloud (contemporaneous SA/SB) as trend filter."""

    def __init__(
        self,
        *,
        tenkan: int = 9,
        kijun: int = 26,
        senkou_b: int = 52,
        size_pct: float = 100.0,
        confidence: float = 0.8,
    ) -> None:
        if not (2 <= tenkan < kijun < senkou_b):
            raise ValueError("need 2 <= tenkan < kijun < senkou_b")
        self._tenkan = tenkan
        self._kijun = kijun
        self._senkou_b = senkou_b
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        if len(ohlcv) < self._senkou_b + 2:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        h = np.array([float(b[2]) for b in ohlcv], dtype=np.float64)
        low = np.array([float(b[3]) for b in ohlcv], dtype=np.float64)
        c = np.array([float(b[4]) for b in ohlcv], dtype=np.float64)
        st = ichimoku_signal_state(h, low, c, tenkan=self._tenkan, kijun=self._kijun, senkou_b=self._senkou_b)
        if st is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        t0, k0, t1, k1, c1, top1, bot1, c0 = st
        above = c1 > top1
        below = c1 < bot1
        if t0 <= k0 and t1 > k1 and above:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="ichimoku tk cross up above cloud",
            )
        if t0 >= k0 and t1 < k1 and below:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="ichimoku tk cross down below cloud",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="ichimoku no signal")


class FibonacciRetracementStrategy:
    """Fade: after touching a Fib level in the swing, bet continuation when price reclaims past the level."""

    def __init__(
        self,
        lookback: int = 50,
        *,
        level_key: str = "0.618",
        size_pct: float = 100.0,
        confidence: float = 0.75,
    ) -> None:
        if lookback < 10:
            raise ValueError("lookback must be >= 10")
        if level_key not in ("0.382", "0.5", "0.618"):
            raise ValueError("level_key must be 0.382, 0.5, or 0.618")
        self._lookback = lookback
        self._level_key = level_key
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        if len(ohlcv) < self._lookback + 2:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        window = ohlcv[-self._lookback :]
        h = np.array([float(b[2]) for b in window], dtype=np.float64)
        low = np.array([float(b[3]) for b in window], dtype=np.float64)
        c = np.array([float(b[4]) for b in window], dtype=np.float64)
        swing_high = float(np.max(h))
        swing_low = float(np.min(low))
        mid = (swing_high + swing_low) / 2.0
        uptrend_swing = float(c[-1]) >= mid
        levels = fibonacci_retracement_levels(swing_high, swing_low, uptrend_swing=uptrend_swing)
        lvl = levels[self._level_key]
        c_prev = float(ohlcv[-2][4])
        c_now = float(ohlcv[-1][4])
        if uptrend_swing:
            # Expect continuation up: long on reclaim above Fib from below
            if c_prev <= lvl < c_now:
                return LLMSignal(
                    action=Action.LONG,
                    size_pct=self._size_pct,
                    confidence=self._confidence,
                    reason=f"fib reclaim up ({self._level_key})",
                )
        else:
            if c_prev >= lvl > c_now:
                return LLMSignal(
                    action=Action.SHORT,
                    size_pct=self._size_pct,
                    confidence=self._confidence,
                    reason=f"fib reclaim down ({self._level_key})",
                )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="fib no cross")


class VolumeProfileStrategy:
    """Breakout vs recent volume-profile POC (fixed-window histogram)."""

    def __init__(
        self,
        profile_bars: int = 48,
        bins: int = 24,
        *,
        size_pct: float = 100.0,
        confidence: float = 0.75,
    ) -> None:
        if profile_bars < 10:
            raise ValueError("profile_bars must be >= 10")
        if bins < 4:
            raise ValueError("bins must be >= 4")
        self._profile_bars = profile_bars
        self._bins = bins
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        if len(ohlcv) < self._profile_bars + 2:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        body = ohlcv[-(self._profile_bars + 2) : -1]
        h = np.array([float(b[2]) for b in body], dtype=np.float64)
        low = np.array([float(b[3]) for b in body], dtype=np.float64)
        c = np.array([float(b[4]) for b in body], dtype=np.float64)
        v = np.array([float(b[5]) for b in body], dtype=np.float64)
        got = volume_profile_poc(h, low, c, v, bins=self._bins)
        if got is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="vp na")
        poc, _, _ = got
        c_prev = float(ohlcv[-2][4])
        c_now = float(ohlcv[-1][4])
        if c_prev <= poc < c_now:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="vp break above poc",
            )
        if c_prev >= poc > c_now:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="vp break below poc",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="vp no break")


class StochasticCrossStrategy:
    """%K crosses %D upward from oversold → long; downward from overbought → short."""

    def __init__(
        self,
        k_period: int = 14,
        d_period: int = 3,
        *,
        oversold: float = 20.0,
        overbought: float = 80.0,
        size_pct: float = 100.0,
        confidence: float = 0.8,
    ) -> None:
        if k_period < 2 or d_period < 1:
            raise ValueError("invalid stochastic periods")
        if not 0.0 < oversold < overbought < 100.0:
            raise ValueError("need 0 < oversold < overbought < 100")
        self._k = k_period
        self._d = d_period
        self._os = oversold
        self._ob = overbought
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        need = self._k + self._d + 5
        if len(ohlcv) < need:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        h = np.array([float(b[2]) for b in ohlcv], dtype=np.float64)
        low = np.array([float(b[3]) for b in ohlcv], dtype=np.float64)
        c = np.array([float(b[4]) for b in ohlcv], dtype=np.float64)
        st = stochastic_cross_state(h, low, c, self._k, self._d)
        if st is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        k0, k1, d0, d1 = st
        if k0 <= d0 and k1 > d1 and k0 < self._os:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="stoch cross up from oversold",
            )
        if k0 >= d0 and k1 < d1 and k0 > self._ob:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="stoch cross down from overbought",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="stoch no signal")


class AtrBreakoutStrategy:
    """Close crosses prior close by ± ``mult`` × Wilder ATR (volatility breakout)."""

    def __init__(
        self,
        atr_period: int = 14,
        *,
        mult: float = 1.5,
        size_pct: float = 100.0,
        confidence: float = 0.75,
    ) -> None:
        if atr_period < 2:
            raise ValueError("ATR period must be >= 2")
        if mult <= 0:
            raise ValueError("mult must be > 0")
        self._p = atr_period
        self._m = mult
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        if len(ohlcv) < self._p + 3:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        h = np.array([float(b[2]) for b in ohlcv], dtype=np.float64)
        low = np.array([float(b[3]) for b in ohlcv], dtype=np.float64)
        c = np.array([float(b[4]) for b in ohlcv], dtype=np.float64)
        atr = atr_wilder_series(h, low, c, self._p)
        if np.isnan(atr[-1]) or np.isnan(atr[-2]):
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        c0 = float(c[-2])
        c1 = float(c[-1])
        band = self._m * float(atr[-2])
        if c1 > c0 + band:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="atr breakout up",
            )
        if c1 < c0 - band:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="atr breakout down",
            )
        return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="atr inside")


# --- test / back-compat exports -------------------------------------------------
def _closes(ohlcv: list[list[float]]) -> list[float]:
    return _closes_list(ohlcv)


def _rsi_series(closes: list[float], period: int) -> list[float | None]:
    return _rsi_series_compat(closes, period)


def _ema_series(closes: list[float], period: int) -> list[float | None]:
    ser = ema_series(np.asarray(closes, dtype=np.float64), period)
    return [None if np.isnan(x) else float(x) for x in ser]


def _macd_cross_pair(
    closes: list[float], fast: int, slow: int, signal_period: int
) -> tuple[float | None, float | None, float | None, float | None]:
    from futures_llm_bot.backtest.indicators import macd_signal_last

    got = macd_signal_last(np.asarray(closes, dtype=np.float64), fast, slow, signal_period)
    if got is None:
        return None, None, None, None
    return got


def _bollinger_bands(closes: list[float], d: int, num_std: float) -> tuple[float | None, float | None, float | None]:
    from futures_llm_bot.backtest.indicators import bollinger_cross_data

    c = np.asarray(closes, dtype=np.float64)
    if c.size < d:
        return None, None, None
    w = c[-d:]
    mid = float(np.mean(w))
    sd = float(np.std(w, ddof=0))
    return mid, mid + num_std * sd, mid - num_std * sd
