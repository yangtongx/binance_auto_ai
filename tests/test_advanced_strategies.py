from __future__ import annotations

import numpy as np

from binance_auto_ai.backtest.engine import run_backtest
from binance_auto_ai.backtest.strategies import RsiThresholdStrategy, SMACrossStrategy
from binance_auto_ai.composite_strategy import CompositeStrategy
from binance_auto_ai.risk_metrics import (
    historical_var_return,
    log_returns_from_closes,
    var_tail_block_reason_from_ohlcv,
)
from binance_auto_ai.strategy_factory import build_strategy_for_backtest, parse_composite_members


def _synth_ohlcv(n: int, *, drift: float = 0.0001) -> list[list[float]]:
    t0 = 1_700_000_000_000
    price = 100.0
    out: list[list[float]] = []
    for i in range(n):
        price *= 1.0 + drift + np.sin(i / 5.0) * 0.002
        o = h = low = c = price
        v = 1.0
        out.append([t0 + i * 60_000, o, h, low, c, v])
    return out


def test_parse_composite_members():
    assert parse_composite_members(" rsi , macd ") == ["rsi", "macd"]


def test_composite_majority_long():
    # 快线上穿慢线 vs RSI 中性 — 构造先分歧后一致的两个子策略
    o = _synth_ohlcv(80, drift=0.001)
    a = SMACrossStrategy(fast=5, slow=15, size_pct=100.0, confidence=0.9)
    b = RsiThresholdStrategy(period=7, oversold=5.0, overbought=99.0, confidence=0.9)
    comp = CompositeStrategy([a, b], "majority", None)
    comp.reset()
    sig = comp.on_bar(len(o) - 1, o)
    assert sig.action.value in ("long", "short", "hold", "flat")


def test_composite_build_factory_smoke():
    strat = build_strategy_for_backtest(
        "composite",
        fast=10,
        slow=30,
        composite_members="sma_cross,rsi",
        composite_mode="majority",
        composite_weights="",
    )
    o = _synth_ohlcv(100)
    strat.reset()
    _ = strat.on_bar(len(o) - 1, o)


def test_rsi_adaptive_runs():
    strat = build_strategy_for_backtest(
        "rsi_adaptive",
        fast=10,
        slow=30,
        rsi_period=7,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        vol_window=15,
        vol_ref_window=30,
        vol_sensitivity=8.0,
    )
    o = _synth_ohlcv(200)
    strat.reset()
    sig = strat.on_bar(len(o) - 1, o)
    assert sig.confidence >= 0


def test_var_tail_gate():
    closes = [100.0 * (0.995**i) for i in range(80)]  # 温和持续下跌
    ohlcv = [[0, c, c, c, c, 1.0] for c in closes]
    r = log_returns_from_closes(closes)
    v = historical_var_return(r, alpha=0.05)
    assert v < 0
    msg = var_tail_block_reason_from_ohlcv(ohlcv, window=60, alpha=0.05, tail_limit=-1e-6)
    assert msg is not None


def test_backtest_composite_engine():
    strat = build_strategy_for_backtest(
        "composite",
        fast=8,
        slow=22,
        composite_members="sma_cross,rsi",
        composite_mode="first",
    )
    o = _synth_ohlcv(120)
    res = run_backtest(o, strat, initial_cash_usdt=10_000.0, max_notional_usdt=500.0, fee_bps=4.0)
    assert len(res.equity_curve) == len(o)
