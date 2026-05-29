"""VaR 回测检验：滚动分位数违约率与 Kupiec 无条件覆盖检验。"""

from __future__ import annotations

import math

import numpy as np

from futures_llm_bot.risk_metrics import historical_var_return


def rolling_var_violations(
    returns: np.ndarray,
    *,
    lookback: int,
    alpha: float,
) -> tuple[int, int, np.ndarray]:
    """
    Compare one-step-ahead realized returns to **rolling** historical VaR.

    At index ``t`` (``t >= lookback``), VaR uses ``returns[t - lookback : t]``,
    violation if ``returns[t] < VaR`` (left-tail exception).

    Returns ``(n_forecasts, n_violations, violation_bool_array aligned to returns)``.
    """
    r = np.asarray(returns, dtype=np.float64).reshape(-1)
    n = r.size
    if n <= lookback + 1:
        return 0, 0, np.array([], dtype=bool)
    viol = np.zeros(n, dtype=bool)
    count = 0
    v = 0
    for t in range(lookback, n):
        hist = r[t - lookback : t]
        var_t = historical_var_return(hist, alpha=alpha)
        if var_t != var_t:
            continue
        count += 1
        if r[t] < var_t:
            viol[t] = True
            v += 1
    return count, v, viol


def kupiec_uc_lr(n: int, x: int, alpha: float) -> float:
    """
    Kupiec (1995) unconditional coverage likelihood-ratio statistic (~ χ²(1) under H0: p = α).

    ``n`` = number of trials, ``x`` = number of violations, expected violation rate ``alpha``.
    """
    if n <= 0 or alpha <= 0.0 or alpha >= 1.0:
        return float("nan")
    if x < 0 or x > n:
        return float("nan")
    p = alpha
    p_hat = x / n
    if p_hat <= 0.0:
        # 边界：用 epsilon 保证数值稳定
        p_hat = 1e-12
    if p_hat >= 1.0:
        p_hat = 1.0 - 1e-12
    try:
        ll0 = x * math.log(p) + (n - x) * math.log(1.0 - p)
        ll1 = x * math.log(p_hat) + (n - x) * math.log(1.0 - p_hat)
        lr = -2.0 * (ll0 - ll1)
        return float(max(lr, 0.0))
    except ValueError:
        return float("nan")


def chi2_1_survival(x: float) -> float:
    """Right-tail P(χ²₁ > x) = 2 (1 - Φ(√x)) for x > 0."""
    if x <= 0:
        return 1.0
    z = math.sqrt(x)
    cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return float(max(0.0, min(1.0, 2.0 * (1.0 - cdf))))


def var_backtest_report(
    returns: np.ndarray,
    *,
    lookback: int,
    alpha: float,
) -> dict[str, float | int | str | None]:
    n, x, _ = rolling_var_violations(returns, lookback=lookback, alpha=alpha)
    hit = x / n if n else float("nan")
    lr = kupiec_uc_lr(n, x, alpha)
    pval = chi2_1_survival(lr) if lr == lr else float("nan")
    crit = 3.841  # 95% χ²(1)
    reject = bool(lr == lr and lr > crit)
    return {
        "lookback": lookback,
        "alpha": alpha,
        "n_forecasts": n,
        "violations": x,
        "violation_rate": hit,
        "expected_rate": alpha,
        "kupiec_lr": lr,
        "kupiec_pvalue_two_sided_proxy": pval,
        "reject_h0_coverage_5pct": reject,
    }
