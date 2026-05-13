from __future__ import annotations

import math

import numpy as np

from futures_llm_bot.var_validation import (
    kupiec_uc_lr,
    rolling_var_violations,
    var_backtest_report,
)


def test_kupiec_under_null_matches_alpha():
    rng = np.random.default_rng(0)
    n_total = 5000
    r = rng.normal(0, 0.01, size=n_total)
    rep = var_backtest_report(r, lookback=200, alpha=0.05)
    assert rep["n_forecasts"] > 0
    rate = rep["violation_rate"]
    assert abs(rate - 0.05) < 0.03  # loose — finite sample
    lr = rep["kupiec_lr"]
    assert lr == lr
    assert lr < 10.0


def test_rolling_violations_count():
    r = np.array([0.01, -0.05, 0.02, -0.03] * 100, dtype=np.float64)
    n, x, v = rolling_var_violations(r, lookback=50, alpha=0.05)
    assert n == r.size - 50
    assert x == int(v.sum())


def test_kupiec_lr_extreme():
    lr0 = kupiec_uc_lr(100, 0, 0.05)
    assert lr0 == lr0 and math.isfinite(lr0)
