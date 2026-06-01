"""技术指标：NumPy 批量计算 + 逐根 K 线 O(1) 增量流（实盘 on_bar 用 Stream 类）。"""

from __future__ import annotations

import numpy as np

_EPS = 1e-18


def closes_array(ohlcv: list[list[float]]) -> np.ndarray:
    if not ohlcv:
        return np.zeros(0, dtype=np.float64)
    return np.array([float(b[4]) for b in ohlcv], dtype=np.float64)


def sma_series(closes: np.ndarray, period: int) -> np.ndarray:
    n = closes.size
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period or period < 1:
        return out
    csum = np.concatenate([[0.0], np.cumsum(closes, dtype=np.float64)])
    out[period - 1 :] = (csum[period:] - csum[:-period]) / period
    return out


def ema_series(closes: np.ndarray, period: int) -> np.ndarray:
    n = closes.size
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period or period < 1:
        return out
    k = 2.0 / (period + 1)
    e = float(np.mean(closes[:period]))
    out[period - 1] = e
    for i in range(period, n):
        e = closes[i] * k + e * (1.0 - k)
        out[i] = e
    return out


def rsi_wilder_series(closes: np.ndarray, period: int) -> np.ndarray:
    n = closes.size
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= period or period < 2:
        return out
    d = np.diff(closes)
    gains = np.maximum(d, 0.0)
    losses = np.maximum(-d, 0.0)
    avg_g = float(np.mean(gains[:period]))
    avg_l = float(np.mean(losses[:period]))

    def r(ag: float, al: float) -> float:
        if al <= _EPS:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    out[period] = r(avg_g, avg_l)
    for idx in range(period, d.size):
        avg_g = (avg_g * (period - 1) + float(gains[idx])) / period
        avg_l = (avg_l * (period - 1) + float(losses[idx])) / period
        out[idx + 1] = r(avg_g, avg_l)
    return out


def macd_signal_last(
    closes: np.ndarray, fast: int, slow: int, signal_period: int
) -> tuple[float, float, float, float] | None:
    if fast >= slow or closes.size < slow + signal_period + 2:
        return None
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    macd = ef - es
    if np.isnan(macd[-1]) or np.isnan(macd[-2]):
        return None
    seq = macd[~np.isnan(macd)]
    if seq.size < signal_period + 2:
        return None
    sig = ema_series(seq, signal_period)
    if np.isnan(sig[-1]) or np.isnan(sig[-2]):
        return None
    return float(seq[-2]), float(sig[-2]), float(seq[-1]), float(sig[-1])


def bollinger_cross_data(
    closes: np.ndarray, period: int, num_std: float
) -> tuple[float, float, float, float, float, float] | None:
    if closes.size < period + 1 or period < 2:
        return None
    w0 = closes[-period - 1 : -1]
    w1 = closes[-period:]
    m0, m1 = float(np.mean(w0)), float(np.mean(w1))
    sd0, sd1 = float(np.std(w0, ddof=0)), float(np.std(w1, ddof=0))
    u0, l0 = m0 + num_std * sd0, m0 - num_std * sd0
    u1, l1 = m1 + num_std * sd1, m1 - num_std * sd1
    return float(closes[-2]), float(closes[-1]), u0, l0, u1, l1


class _RollingSMA:
    __slots__ = ("_p", "_buf", "_s")

    def __init__(self, period: int) -> None:
        self._p = period
        self._buf: list[float] = []
        self._s = 0.0

    def clear(self) -> None:
        self._buf.clear()
        self._s = 0.0

    def seed_tail(self, values: np.ndarray) -> None:
        self.clear()
        for x in values:
            self.push(float(x))

    def push(self, x: float) -> float | None:
        self._buf.append(x)
        self._s += x
        if len(self._buf) > self._p:
            self._s -= self._buf.pop(0)
        if len(self._buf) < self._p:
            return None
        return self._s / self._p


class SMACrossStream:
    """快慢 SMA 增量流；``cross()`` 返回上一根/当前快慢线值，用于判断金叉死叉。"""

    __slots__ = ("_fast", "_slow", "_rf", "_rs", "_fp", "_sp", "_fn", "_sn", "_n", "_key")

    def __init__(self, fast: int, slow: int) -> None:
        self._fast = fast
        self._slow = slow
        self._rf = _RollingSMA(fast)
        self._rs = _RollingSMA(slow)
        self._fp = self._sp = self._fn = self._sn = float("nan")
        self._n: int | None = None
        self._key: tuple[float, ...] = ()

    def reset(self) -> None:
        self._rf.clear()
        self._rs.clear()
        self._fp = self._sp = self._fn = self._sn = float("nan")
        self._n = None
        self._key = ()

    def _seed_numpy(self, c: np.ndarray) -> None:
        self.reset()
        if c.size < self._slow + 1:
            return
        sf = sma_series(c, self._fast)
        ss = sma_series(c, self._slow)
        if np.isnan(sf[-2]) or np.isnan(ss[-2]) or np.isnan(sf[-1]) or np.isnan(ss[-1]):
            return
        self._fp, self._sp = float(sf[-2]), float(ss[-2])
        self._fn, self._sn = float(sf[-1]), float(ss[-1])
        self._rf.seed_tail(c[-self._fast :])
        self._rs.seed_tail(c[-self._slow :])
        self._n = c.size
        self._key = tuple(float(x) for x in c[-self._slow :])

    def ensure(self, closes: list[float]) -> None:
        c = np.asarray(closes, dtype=np.float64)
        if c.size < self._slow + 1:
            self.reset()
            return
        if (
            self._n is not None
            and c.size == self._n + 1
            and self._key
            and tuple(c[-self._slow - 1 : -1]) == self._key
        ):
            self._advance(float(c[-1]))
            self._n = c.size
            self._key = tuple(float(x) for x in c[-self._slow :])
            return
        self._seed_numpy(c)

    def _advance(self, price: float) -> None:
        self._fp, self._sp = self._fn, self._sn
        self._fn = self._rf.push(price)
        self._sn = self._rs.push(price)
        if self._fn is None or self._sn is None:
            self._fp = self._sp = self._fn = self._sn = float("nan")

    def cross(self) -> tuple[float, float, float, float] | None:
        if any(np.isnan([self._fp, self._sp, self._fn, self._sn])):
            return None
        return self._fp, self._sp, self._fn, self._sn


class RSIWilderStream:
    """Wilder RSI 增量流，避免每根 K 线全量重算。"""

    __slots__ = ("_p", "_avg_g", "_avg_l", "_prev_c", "_rsi", "_n", "_key")

    def __init__(self, period: int) -> None:
        self._p = period
        self._avg_g = self._avg_l = 0.0
        self._prev_c: float | None = None
        self._rsi = float("nan")
        self._n: int | None = None
        self._key: tuple[float, ...] = ()

    def reset(self) -> None:
        self._avg_g = self._avg_l = 0.0
        self._prev_c = None
        self._rsi = float("nan")
        self._n = None
        self._key = ()

    def _seed_numpy(self, c: np.ndarray) -> None:
        self.reset()
        if c.size <= self._p:
            return
        ser = rsi_wilder_series(c, self._p)
        if np.isnan(ser[-1]):
            return
        self._rsi = float(ser[-1])
        self._prev_c = float(c[-1])
        d = np.diff(c)
        g = np.maximum(d, 0.0)
        ell = np.maximum(-d, 0.0)
        self._avg_g = float(np.mean(g[: self._p]))
        self._avg_l = float(np.mean(ell[: self._p]))
        for idx in range(self._p, g.size):
            self._avg_g = (self._avg_g * (self._p - 1) + float(g[idx])) / self._p
            self._avg_l = (self._avg_l * (self._p - 1) + float(ell[idx])) / self._p
        self._n = c.size
        self._key = tuple(float(x) for x in c[-self._p :])

    def ensure(self, closes: list[float]) -> None:
        c = np.asarray(closes, dtype=np.float64)
        if c.size <= self._p:
            self.reset()
            return
        if (
            self._n is not None
            and c.size == self._n + 1
            and self._key
            and tuple(c[-self._p - 1 : -1]) == self._key
        ):
            self._advance(float(c[-1]))
            self._n = c.size
            self._key = tuple(float(x) for x in c[-self._p :])
            return
        self._seed_numpy(c)

    def _advance(self, close: float) -> None:
        if self._prev_c is None:
            self._prev_c = close
            return
        d = close - self._prev_c
        self._prev_c = close
        gg = max(d, 0.0)
        ll = max(-d, 0.0)
        self._avg_g = (self._avg_g * (self._p - 1) + gg) / self._p
        self._avg_l = (self._avg_l * (self._p - 1) + ll) / self._p
        if self._avg_l <= _EPS:
            self._rsi = 100.0
        else:
            self._rsi = 100.0 - 100.0 / (1.0 + self._avg_g / self._avg_l)

    def rsi(self) -> float | None:
        if np.isnan(self._rsi):
            return None
        return float(self._rsi)


class MACDStream:
    """MACD 线与信号线增量流。"""
    __slots__ = (
        "_fast",
        "_slow",
        "_sig_p",
        "_kf",
        "_ks",
        "_k_sig",
        "_ef",
        "_es",
        "_mp",
        "_sp",
        "_mn",
        "_sn",
        "_n",
        "_key",
    )

    def __init__(self, fast: int, slow: int, signal_period: int) -> None:
        self._fast = fast
        self._slow = slow
        self._sig_p = signal_period
        self._kf = 2.0 / (fast + 1)
        self._ks = 2.0 / (slow + 1)
        self._k_sig = 2.0 / (signal_period + 1)
        self._ef = self._es = float("nan")
        self._mp = self._sp = self._mn = self._sn = float("nan")
        self._n: int | None = None
        self._key: tuple[float, ...] = ()

    def reset(self) -> None:
        self._ef = self._es = float("nan")
        self._mp = self._sp = self._mn = self._sn = float("nan")
        self._n = None
        self._key = ()

    def _seed_numpy(self, c: np.ndarray) -> None:
        self.reset()
        got = macd_signal_last(c, self._fast, self._slow, self._sig_p)
        if got is None:
            return
        mp, sp, mn, sn = got
        ef = ema_series(c, self._fast)
        es = ema_series(c, self._slow)
        self._ef = float(ef[-1])
        self._es = float(es[-1])
        self._mp, self._sp, self._mn, self._sn = mp, sp, mn, sn
        self._n = c.size
        self._key = tuple(float(x) for x in c[-self._slow :])

    def ensure(self, closes: list[float]) -> None:
        c = np.asarray(closes, dtype=np.float64)
        need = self._slow + self._sig_p + 2
        if c.size < need:
            self.reset()
            return
        if (
            self._n is not None
            and c.size == self._n + 1
            and self._key
            and tuple(c[-self._slow - 1 : -1]) == self._key
        ):
            self._advance(float(c[-1]))
            self._n = c.size
            self._key = tuple(float(x) for x in c[-self._slow :])
            return
        self._seed_numpy(c)

    def _advance(self, price: float) -> None:
        self._mp, self._sp = self._mn, self._sn
        self._ef = price * self._kf + self._ef * (1.0 - self._kf)
        self._es = price * self._ks + self._es * (1.0 - self._ks)
        m_now = self._ef - self._es
        sig_now = m_now * self._k_sig + self._sp * (1.0 - self._k_sig)
        self._mn, self._sn = m_now, sig_now

    def cross(self) -> tuple[float, float, float, float] | None:
        if any(np.isnan([self._mp, self._sp, self._mn, self._sn])):
            return None
        return self._mp, self._sp, self._mn, self._sn


class BollingerStream:
    """布林带上下轨增量流。"""
    __slots__ = ("_period", "_std", "_tail_closes", "_n", "_key")

    def __init__(self, period: int, num_std: float) -> None:
        self._period = period
        self._std = num_std
        self._tail_closes: list[float] = []
        self._n: int | None = None
        self._key: tuple[float, ...] = ()

    def reset(self) -> None:
        self._tail_closes.clear()
        self._n = None
        self._key = ()

    def _seed_numpy(self, c: np.ndarray) -> None:
        self.reset()
        if bollinger_cross_data(c, self._period, self._std) is None:
            return
        self._tail_closes = [float(x) for x in c[-(self._period + 1) :]]
        self._n = c.size
        self._key = tuple(float(x) for x in c[-self._period - 1 : -1])

    def ensure(self, closes: list[float]) -> None:
        c = np.asarray(closes, dtype=np.float64)
        if c.size < self._period + 1:
            self.reset()
            return
        if (
            self._n is not None
            and c.size == self._n + 1
            and self._key
            and tuple(c[-self._period - 1 : -1]) == self._key
        ):
            self._tail_closes = [float(x) for x in c[-(self._period + 1) :]]
            self._n = c.size
            self._key = tuple(float(x) for x in c[-self._period - 1 : -1])
            return
        self._seed_numpy(c)

    def cross_bounds(self) -> tuple[float, float, float, float, float, float] | None:
        if len(self._tail_closes) < self._period + 1:
            return None
        arr = np.array(self._tail_closes, dtype=np.float64)
        return bollinger_cross_data(arr, self._period, self._std)


def ichimoku_lines(
    high: np.ndarray,
    low: np.ndarray,
    *,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Contemporaneous Ichimoku lines (no forward shift). Cloud = [min(sa,sb), max(sa,sb)].

    ``senkou_a = (tenkan + kijun) / 2``; ``senkou_b`` = midpoint of senkou_b-period Donchian.
    """
    n = high.size
    ten = np.full(n, np.nan, dtype=np.float64)
    kij = np.full(n, np.nan, dtype=np.float64)
    sb = np.full(n, np.nan, dtype=np.float64)
    sa = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        if i >= tenkan - 1:
            sl = i - tenkan + 1
            ten[i] = (float(np.max(high[sl : i + 1])) + float(np.min(low[sl : i + 1]))) / 2.0
        if i >= kijun - 1:
            sl = i - kijun + 1
            kij[i] = (float(np.max(high[sl : i + 1])) + float(np.min(low[sl : i + 1]))) / 2.0
        if i >= senkou_b - 1:
            sl = i - senkou_b + 1
            sb[i] = (float(np.max(high[sl : i + 1])) + float(np.min(low[sl : i + 1]))) / 2.0
        if not np.isnan(ten[i]) and not np.isnan(kij[i]):
            sa[i] = (ten[i] + kij[i]) / 2.0
    return ten, kij, sa, sb


def ichimoku_signal_state(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
) -> tuple[float, float, float, float, float, float, float, float] | None:
    """Return (t0,k0,t1,k1,c1,top1,bot1) for bars -2 and -1; None if not enough data."""
    if close.size < max(senkou_b, kijun, tenkan) + 2:
        return None
    ten, kij, sa, sb = ichimoku_lines(high, low, tenkan=tenkan, kijun=kijun, senkou_b=senkou_b)
    if any(np.isnan([ten[-1], kij[-1], sa[-1], sb[-1], ten[-2], kij[-2], close[-1]])):
        return None
    top1 = max(float(sa[-1]), float(sb[-1]))
    bot1 = min(float(sa[-1]), float(sb[-1]))
    return float(ten[-2]), float(kij[-2]), float(ten[-1]), float(kij[-1]), float(close[-1]), top1, bot1, float(close[-2])


def fibonacci_retracement_levels(swing_high: float, swing_low: float, *, uptrend_swing: bool) -> dict[str, float]:
    """Return 0.382 / 0.5 / 0.618 retracement prices from swing leg."""
    diff = swing_high - swing_low
    if uptrend_swing:
        # 自高点回落
        return {
            "0.382": swing_high - 0.382 * diff,
            "0.5": swing_high - 0.5 * diff,
            "0.618": swing_high - 0.618 * diff,
        }
    # 下跌趋势中自低点反弹
    return {
        "0.382": swing_low + 0.382 * diff,
        "0.5": swing_low + 0.5 * diff,
        "0.618": swing_low + 0.618 * diff,
    }


def volume_profile_poc(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    *,
    bins: int,
) -> tuple[float, float, float] | None:
    """Point of control (POC): price bin center with greatest volume×typical_price weight.

    Returns (poc_price, range_low, range_high) or None.
    """
    if high.size < 2 or bins < 2:
        return None
    typ = (high + low + close) / 3.0
    lo = float(np.min(low))
    hi = float(np.max(high))
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    vol_w = np.zeros(bins, dtype=np.float64)
    for i in range(typ.size):
        b = int(np.clip(np.searchsorted(edges, typ[i], side="right") - 1, 0, bins - 1))
        vol_w[b] += float(volume[i])
    if np.max(vol_w) <= 0:
        return None
    ix = int(np.argmax(vol_w))
    poc = float((edges[ix] + edges[ix + 1]) / 2.0)
    return poc, lo, hi


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Wilder true range (``close`` shifted: prev close vs current H/L)."""
    n = close.size
    tr = np.full(n, np.nan, dtype=np.float64)
    if n < 2:
        return tr
    pc = np.concatenate([[close[0]], close[:-1]])
    tr[0] = float(high[0] - low[0])
    hl = high[1:] - low[1:]
    hpc = np.abs(high[1:] - pc[1:])
    lpc = np.abs(low[1:] - pc[1:])
    tr[1:] = np.maximum(np.maximum(hl, hpc), lpc)
    return tr


def atr_wilder_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder ATR (RMA of true range)."""
    n = close.size
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period + 1 or period < 1:
        return out
    tr = true_range(high, low, close)
    # 首个 ATR：从索引 1 起对前 `period` 个 TR 取简单均值
    seed = float(np.nanmean(tr[1 : period + 1]))
    out[period] = seed
    a = seed
    for i in range(period + 1, n):
        a = (a * (period - 1) + float(tr[i])) / period
        out[i] = a
    return out


def stochastic_pct_k_pct_d(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    k_period: int,
    d_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Fast %K and %D (SMA of %K). Classic 0–100 oscillator."""
    n = close.size
    pct_k = np.full(n, np.nan, dtype=np.float64)
    for i in range(k_period - 1, n):
        sl = slice(i - k_period + 1, i + 1)
        hh = float(np.max(high[sl]))
        ll = float(np.min(low[sl]))
        denom = hh - ll
        if denom <= _EPS:
            pct_k[i] = 50.0
        else:
            pct_k[i] = (float(close[i]) - ll) / denom * 100.0
    pct_d = np.full(n, np.nan, dtype=np.float64)
    for i in range(k_period + d_period - 2, n):
        sl = slice(i - d_period + 1, i + 1)
        chunk = pct_k[sl]
        if np.any(np.isnan(chunk)):
            continue
        pct_d[i] = float(np.mean(chunk))
    return pct_k, pct_d


def stochastic_cross_state(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    k_period: int,
    d_period: int,
) -> tuple[float, float, float, float] | None:
    """``(k0,k1,d0,d1)`` at bars -2 and -1 for cross logic; None if undefined."""
    need = k_period + d_period + 2
    if close.size < need:
        return None
    k, d = stochastic_pct_k_pct_d(high, low, close, k_period, d_period)
    if any(np.isnan([k[-2], k[-1], d[-2], d[-1]])):
        return None
    return float(k[-2]), float(k[-1]), float(d[-2]), float(d[-1])
