"""Example deterministic strategies (rule-based, reproducible)."""

from __future__ import annotations

from futures_llm_bot.schemas import Action, LLMSignal


def _closes(ohlcv: list[list[float]]) -> list[float]:
    return [float(bar[4]) for bar in ohlcv]


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def _stdev(values: list[float]) -> float:
    if not values:
        return 0.0
    m = sum(values) / len(values)
    var = sum((x - m) ** 2 for x in values) / len(values)
    return var ** 0.5


def _ema_series(closes: list[float], period: int) -> list[float | None]:
    """EMA aligned to ``closes``; first valid value at index ``period - 1`` (seeded with SMA)."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(closes[:period]) / period
    out[period - 1] = seed
    e = seed
    for i in range(period, n):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def _rsi_series(closes: list[float], period: int) -> list[float | None]:
    """Wilder RSI per close index; first numeric RSI at index ``period`` (needs ``period+1`` closes)."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period

    def r(ag: float, al: float) -> float:
        if al <= 1e-18:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    out[period] = r(avg_g, avg_l)
    for idx in range(period, len(deltas)):
        avg_g = (avg_g * (period - 1) + gains[idx]) / period
        avg_l = (avg_l * (period - 1) + losses[idx]) / period
        out[idx + 1] = r(avg_g, avg_l)
    return out


def _macd_cross_pair(
    closes: list[float], fast: int, slow: int, signal_period: int
) -> tuple[float | None, float | None, float | None, float | None]:
    """(macd_prev, sig_prev, macd_now, sig_now) at last bar; ``None`` if warmup."""
    if fast >= slow or len(closes) < slow + signal_period + 2:
        return None, None, None, None
    ef = _ema_series(closes, fast)
    es = _ema_series(closes, slow)
    macd_seq: list[float] = []
    for j in range(len(closes)):
        if ef[j] is None or es[j] is None:
            continue
        macd_seq.append(ef[j] - es[j])
    if len(macd_seq) < signal_period + 2:
        return None, None, None, None
    sig = _ema_series(macd_seq, signal_period)
    i_now = len(macd_seq) - 1
    i_prev = i_now - 1
    m_prev, m_now = macd_seq[i_prev], macd_seq[i_now]
    sp = sig[i_prev]
    sn = sig[i_now]
    if sp is None or sn is None:
        return None, None, None, None
    return m_prev, sp, m_now, sn


def _bollinger_bands(closes: list[float], d: int, num_std: float) -> tuple[float | None, float | None, float | None]:
    """(mid, upper, lower) for **current** close using last ``d`` closes."""
    if len(closes) < d:
        return None, None, None
    window = closes[-d:]
    mid = sum(window) / d
    sd = _stdev(window)
    u = mid + num_std * sd
    low = mid - num_std * sd
    return mid, u, low


class SMACrossStrategy:
    """Fast SMA crosses above slow → long; cross below → short; else hold.

    Outputs `LLMSignal` so the same schema can feed live risk/execution later.
    """

    def __init__(self, fast: int = 10, slow: int = 30, *, size_pct: float = 100.0, confidence: float = 0.8) -> None:
        if fast >= slow:
            raise ValueError("fast period must be < slow period")
        self._fast = fast
        self._slow = slow
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        c = _closes(ohlcv)
        if len(c) < self._slow + 1:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")

        prev_c = c[:-1]
        f_prev, s_prev = _sma(prev_c, self._fast), _sma(prev_c, self._slow)
        f_now, s_now = _sma(c, self._fast), _sma(c, self._slow)
        if f_prev is None or s_prev is None or f_now is None or s_now is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")

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
        self._period = period
        self._os = oversold
        self._ob = overbought
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        c = _closes(ohlcv)
        series = _rsi_series(c, self._period)
        rsi = series[-1] if series else None
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
        self._fast = fast
        self._slow = slow
        self._sig = signal_period
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        c = _closes(ohlcv)
        mp, sp, mn, sn = _macd_cross_pair(c, self._fast, self._slow, self._sig)
        if mp is None or sp is None or mn is None or sn is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
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
        self._period = period
        self._std = num_std
        self._size_pct = size_pct
        self._confidence = confidence

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        c = _closes(ohlcv)
        if len(c) < self._period + 1:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        _, u_prev, l_prev = _bollinger_bands(c[:-1], self._period, self._std)
        _, u_now, l_now = _bollinger_bands(c, self._period, self._std)
        if u_prev is None or l_prev is None or u_now is None or l_now is None:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="warmup")
        prev_c, now_c = c[-2], c[-1]
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
