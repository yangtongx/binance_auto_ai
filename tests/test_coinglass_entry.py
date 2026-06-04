from __future__ import annotations

from binance_auto_ai.coinglass_derivatives import CoinGlassMarketContext
from binance_auto_ai.coinglass_entry import (
    entry_cg_alignment,
    entry_cg_block_reason,
    pick_best_with_coinglass,
)
from binance_auto_ai.config import Settings
from binance_auto_ai.schemas import Action, LLMSignal


def _settings(**kwargs: object) -> Settings:
    base = {
        "coinglass_api_key": "k",
        "coinglass_derivatives_on": True,
        "entry_cg_on": True,
        "entry_cg_weight": 0.4,
        "entry_cg_liq_min_usd": 500_000.0,
        "entry_cg_block_against": True,
        "entry_cg_block_dist_pct": 2.0,
    }
    base.update(kwargs)
    return Settings.model_validate(base)


def _sig(action: Action, confidence: float) -> LLMSignal:
    return LLMSignal(action=action, size_pct=100.0, confidence=confidence, reason="t")


def test_long_blocked_near_below_cluster() -> None:
    ctx = CoinGlassMarketContext(
        symbol="X/USDT:USDT",
        coin="X",
        pair="XUSDT",
        mark_price=100.0,
        liq_notional_below_mark_usd=2_000_000.0,
        liq_nearest_long_price=99.0,
    )
    reason = entry_cg_block_reason("long", ctx, _settings())
    assert reason is not None
    assert "cg_entry_block" in reason


def test_long_prefers_above_cluster_in_pick() -> None:
    s = _settings(entry_cg_weight=0.5)
    signals = {
        "A/USDT:USDT": _sig(Action.LONG, 0.70),
        "B/USDT:USDT": _sig(Action.LONG, 0.70),
    }
    contexts = {
        "A/USDT:USDT": CoinGlassMarketContext(
            symbol="A/USDT:USDT",
            coin="A",
            pair="AUSDT",
            mark_price=100.0,
            liq_notional_below_mark_usd=3_000_000.0,
            liq_nearest_long_price=99.5,
        ),
        "B/USDT:USDT": CoinGlassMarketContext(
            symbol="B/USDT:USDT",
            coin="B",
            pair="BUSDT",
            mark_price=100.0,
            liq_notional_above_mark_usd=3_000_000.0,
            liq_heatmap_above_usd=2_000_000.0,
        ),
    }
    pick = pick_best_with_coinglass(
        signals,
        candidates_order=["A/USDT:USDT", "B/USDT:USDT"],
        min_confidence=0.55,
        contexts=contexts,
        settings=s,
    )
    assert pick is not None
    assert pick.symbol == "B/USDT:USDT"


def test_alignment_higher_with_favorable_liq() -> None:
    ctx_good = CoinGlassMarketContext(
        symbol="X/USDT:USDT",
        coin="X",
        pair="XUSDT",
        mark_price=100.0,
        liq_notional_above_mark_usd=5_000_000.0,
    )
    ctx_bad = CoinGlassMarketContext(
        symbol="X/USDT:USDT",
        coin="X",
        pair="XUSDT",
        mark_price=100.0,
        liq_notional_below_mark_usd=5_000_000.0,
        liq_nearest_long_price=99.0,
    )
    s = _settings()
    assert entry_cg_alignment("long", ctx_good, s) > entry_cg_alignment("long", ctx_bad, s)
