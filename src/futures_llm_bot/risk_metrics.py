"""风险指标：历史 VaR 尾部、收益相关性、波动率；供 RISK_VAR_BLOCK 与 rsi_adaptive 使用。"""

from __future__ import annotations

import numpy as np


def log_returns_from_closes(closes: list[float] | np.ndarray) -> np.ndarray:
    """Log returns r_t = ln(C_t / C_{t-1}); length len(closes)-1."""
    c = np.asarray(closes, dtype=np.float64)
    if c.size < 2:
        return np.array([], dtype=np.float64)
    r = np.diff(np.log(np.maximum(c, 1e-12)))
    return r.astype(np.float64)


def historical_var_return(returns: np.ndarray, *, alpha: float = 0.05) -> float:
    """Empirical VaR in **return** space: the ``alpha`` lower quantile (more negative = worse left tail)."""
    if returns.size < 5:
        return float("nan")
    a = float(alpha)
    if not 0.0 < a < 1.0:
        raise ValueError("alpha must be in (0,1)")
    return float(np.quantile(returns, a))


def pearson_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson r; nan if insufficient variance or length mismatch."""
    if x.size != y.size or x.size < 3:
        return float("nan")
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    sx = float(np.std(x, ddof=0))
    sy = float(np.std(y, ddof=0))
    if sx < 1e-15 or sy < 1e-15:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def realized_vol_ewma(returns: np.ndarray, *, span: int = 20) -> float:
    """Simple EWMA sigma of returns (last estimate). For scaling; not annualized."""
    if returns.size < 3:
        return float("nan")
    lam = 2.0 / (float(span) + 1.0)
    var = float(np.var(returns[: max(5, min(20, returns.size))], ddof=0))
    for rv in returns:
        var = lam * (rv * rv) + (1.0 - lam) * var
    return float(np.sqrt(max(var, 0.0)))


def rolling_median_realized_vol(
    closes: list[float] | np.ndarray,
    *,
    vol_window: int,
    ref_window: int,
) -> tuple[float, float]:
    """Return (current_sigma, reference_median_sigma) from log-return rolling windows."""
    c = np.asarray(closes, dtype=np.float64)
    if c.size < vol_window + ref_window + 2:
        return float("nan"), float("nan")
    r = log_returns_from_closes(c)
    if r.size < vol_window + ref_window:
        return float("nan"), float("nan")
    sigmas: list[float] = []
    vw = int(vol_window)
    for j in range(vw - 1, r.size):
        seg = r[j - vw + 1 : j + 1]
        sigmas.append(float(np.std(seg, ddof=0)))
    sig = np.asarray(sigmas, dtype=np.float64)
    if sig.size < 2:
        return float("nan"), float("nan")
    cur = float(sig[-1])
    rw = int(ref_window)
    ref_slice = sig[-rw:] if sig.size >= rw else sig
    med = float(np.median(ref_slice))
    return cur, med


def var_tail_block_reason_from_ohlcv(
    ohlcv: list[list[float]],
    *,
    window: int,
    alpha: float,
    tail_limit: float,
) -> str | None:
    """
    经验 VaR 门控：近期对数收益分位数若差于 tail_limit（如 -0.02），则禁止开新仓。

    返回简短中文原因字符串，否则 None。
    """
    if window <= 0:
        return None
    if len(ohlcv) < window + 1:
        return None
    closes = [float(b[4]) for b in ohlcv[-(window + 1) :]]
    r = log_returns_from_closes(closes)
    if r.size < 5:
        return None
    var_r = historical_var_return(r, alpha=alpha)
    if var_r != var_r:  # nan
        return None
    if var_r <= tail_limit:
        return (
            f"var tail {var_r:.4f} at alpha={alpha} <= limit {tail_limit:.4f} "
            f"(window={window} bars)"
        )
    return None


def aligned_log_return_correlation(
    ohlcv_a: list[list[float]],
    ohlcv_b: list[list[float]],
    *,
    max_pairs: int = 500,
) -> float:
    """Pearson correlation of aligned **log returns** (tail ``max_pairs`` bars each)."""
    ca = [float(b[4]) for b in ohlcv_a[-max_pairs:]]
    cb = [float(b[4]) for b in ohlcv_b[-max_pairs:]]
    n = min(len(ca), len(cb))
    if n < 4:
        return float("nan")
    ca, cb = ca[-n:], cb[-n:]
    ra = log_returns_from_closes(ca)
    rb = log_returns_from_closes(cb)
    m = min(ra.size, rb.size)
    if m < 3:
        return float("nan")
    return pearson_correlation(ra[-m:], rb[-m:])

