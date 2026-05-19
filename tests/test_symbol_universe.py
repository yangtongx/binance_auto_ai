"""Tests for auto candidate universe selection."""

from __future__ import annotations

from futures_llm_bot.config import Settings
from futures_llm_bot.symbol_universe import (
    affordable_max_notional_usdt,
    is_auto_symbol_candidates,
    parse_rank_metrics,
    parse_rank_weights,
    select_top_usdm_candidates,
)


class _FakeEx:
    markets: dict = {}

    def fetch_tickers(self) -> dict:
        return getattr(self, "_tickers", {})

    def market(self, symbol: str) -> dict:
        return self.markets[symbol]


def _mkt(sym: str, *, base: str | None = None) -> dict:
    b = base or sym.split("/")[0]
    return {
        "symbol": sym,
        "quote": "USDT",
        "swap": True,
        "linear": True,
        "active": True,
        "limits": {"amount": {"min": 1.0}},
        "precision": {"amount": 1.0},
    }


def test_is_auto_token() -> None:
    assert is_auto_symbol_candidates("auto")
    assert is_auto_symbol_candidates("TOP")
    assert not is_auto_symbol_candidates("DOGE/USDT:USDT")


def test_select_top_by_abs_change_excludes_btc() -> None:
    ex = _FakeEx()
    ex.markets = {
        "BTC/USDT:USDT": _mkt("BTC/USDT:USDT"),
        "DOGE/USDT:USDT": _mkt("DOGE/USDT:USDT"),
        "SOL/USDT:USDT": _mkt("SOL/USDT:USDT"),
        "XRP/USDT:USDT": _mkt("XRP/USDT:USDT"),
    }
    ex._tickers = {
        "BTC/USDT:USDT": {"quoteVolume": 9e9, "last": 80000.0, "percentage": 1.0},
        "DOGE/USDT:USDT": {"quoteVolume": 2e8, "last": 0.2, "percentage": 8.0},
        "SOL/USDT:USDT": {"quoteVolume": 1e9, "last": 150.0, "percentage": 3.0},
        "XRP/USDT:USDT": {"quoteVolume": 5e8, "last": 0.5, "percentage": 5.0},
    }
    s = Settings.model_construct(
        symbol_mode="signal_pick",
        symbol_candidates="auto",
        symbol_candidates_count=3,
        symbol_candidates_rank_by="abs_change",
        symbol_candidates_min_quote_volume_usdt=0.0,
        symbol_candidates_exclude="BTC/USDT:USDT",
        symbol_candidates_filter_min_notional=False,
        max_notional_usdt=10_000.0,
        position_sizing="fixed",
        strategy_size_pct=100.0,
    )
    picked = select_top_usdm_candidates(ex, s)  # type: ignore[arg-type]
    assert "BTC/USDT:USDT" not in picked
    assert picked[0] == "DOGE/USDT:USDT"
    assert len(picked) == 3


def test_parse_rank_metrics_composite() -> None:
    assert parse_rank_metrics("abs_change, open_interest, liquidity, volume") == [
        "abs_change",
        "open_interest",
        "quote_volume",
    ]
    assert parse_rank_weights(["abs_change", "open_interest"], "3,1") == [0.75, 0.25]


def test_composite_rank_prefers_high_on_both_metrics() -> None:
    ex = _FakeEx()
    ex.markets = {
        "AAA/USDT:USDT": _mkt("AAA/USDT:USDT"),
        "BBB/USDT:USDT": _mkt("BBB/USDT:USDT"),
        "CCC/USDT:USDT": _mkt("CCC/USDT:USDT"),
    }
    ex._tickers = {
        "AAA/USDT:USDT": {"last": 1.0, "percentage": 2.0, "info": {"openInterest": "100"}},
        "BBB/USDT:USDT": {"last": 1.0, "percentage": 10.0, "info": {"openInterest": "50"}},
        "CCC/USDT:USDT": {"last": 1.0, "percentage": 1.0, "info": {"openInterest": "500"}},
    }
    s = Settings.model_construct(
        symbol_mode="signal_pick",
        symbol_candidates="auto",
        symbol_candidates_count=2,
        symbol_candidates_rank_by="abs_change,open_interest",
        symbol_candidates_rank_weights="0.5,0.5",
        symbol_candidates_min_quote_volume_usdt=0.0,
        symbol_candidates_exclude="",
        symbol_candidates_filter_min_notional=False,
        max_notional_usdt=10_000.0,
        position_sizing="fixed",
        strategy_size_pct=100.0,
    )
    picked = select_top_usdm_candidates(ex, s)  # type: ignore[arg-type]
    assert len(picked) == 2
    assert picked[0] == "BBB/USDT:USDT"


def test_affordable_margin_sizing_cap() -> None:
    s = Settings.model_construct(
        max_notional_usdt=10_000.0,
        position_sizing="available_margin_leverage",
        leverage=150.0,
        strategy_size_pct=100.0,
    )
    assert affordable_max_notional_usdt(s, equity_usdt=44.0, available_margin_usdt=40.0) == 6000.0
