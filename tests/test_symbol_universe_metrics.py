"""Tests for momentum / funding rank metrics and rank-percentile normalization."""

from __future__ import annotations

from binance_auto_ai.config import Settings
from binance_auto_ai.symbol_universe import (
    _momentum_strength,
    _rank_normalize,
    parse_rank_metrics,
    select_top_usdm_candidates,
)


def _mkt(sym: str) -> dict:
    return {
        "symbol": sym,
        "quote": "USDT",
        "swap": True,
        "linear": True,
        "active": True,
        "limits": {"amount": {"min": 1.0}},
        "precision": {"amount": 1.0},
    }


def _rising_ohlcv(n: int, start: float = 100.0, step: float = 1.0) -> list[list[float]]:
    return [[i, start + i * step, start + i * step, start + i * step, start + i * step, 1.0] for i in range(n)]


def _flat_ohlcv(n: int, price: float = 100.0) -> list[list[float]]:
    return [[i, price, price, price, price, 1.0] for i in range(n)]


class _FakeOhlcvEx:
    def __init__(self, markets: dict, tickers: dict, ohlcv: dict, funding: dict | None = None) -> None:
        self.markets = markets
        self._tickers = tickers
        self._ohlcv = ohlcv
        self._funding = funding or {}

    def fetch_tickers(self) -> dict:
        return self._tickers

    def market(self, symbol: str) -> dict:
        return self.markets[symbol]

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        return self._ohlcv[symbol][-limit:]

    def fetch_funding_rates(self) -> dict:
        return self._funding


# --- rank-percentile normalization (#3) ---


def test_rank_normalize_basic_and_ties() -> None:
    assert _rank_normalize([1.0, 2.0, 3.0]) == [0.0, 0.5, 1.0]
    assert _rank_normalize([5.0, 5.0, 5.0]) == [0.5, 0.5, 0.5]
    # ties take the average rank
    assert _rank_normalize([10.0, 10.0, 0.0]) == [0.75, 0.75, 0.0]


def test_rank_normalize_is_outlier_robust() -> None:
    # a single huge outlier must not crush the rest toward 0 (unlike min-max)
    assert _rank_normalize([1.0, 2.0, 1e9]) == _rank_normalize([1.0, 2.0, 3.0])


# --- momentum metric (#1) ---


def test_momentum_strength_trend_vs_flat() -> None:
    rising = _rising_ohlcv(70)
    flat = _flat_ohlcv(70)
    s_rise = _momentum_strength(rising, fast=10, slow=30)
    s_flat = _momentum_strength(flat, fast=10, slow=30)
    assert s_rise is not None and s_flat is not None
    assert s_rise > s_flat
    assert s_flat == 0.0


def test_momentum_strength_needs_enough_bars() -> None:
    assert _momentum_strength(_rising_ohlcv(10), fast=10, slow=30) is None


def test_select_by_momentum_prefers_trending_symbol() -> None:
    markets = {
        "TREND/USDT:USDT": _mkt("TREND/USDT:USDT"),
        "FLAT/USDT:USDT": _mkt("FLAT/USDT:USDT"),
    }
    tickers = {
        "TREND/USDT:USDT": {"last": 169.0, "quoteVolume": 5e8, "percentage": 4.0},
        "FLAT/USDT:USDT": {"last": 100.0, "quoteVolume": 9e8, "percentage": 0.1},
    }
    ohlcv = {
        "TREND/USDT:USDT": _rising_ohlcv(70),
        "FLAT/USDT:USDT": _flat_ohlcv(70),
    }
    ex = _FakeOhlcvEx(markets, tickers, ohlcv)
    s = Settings.model_construct(
        symbol_mode="signal_pick",
        symbol_candidates="auto",
        symbol_candidates_count=2,
        symbol_candidates_rank_by="momentum",
        symbol_candidates_rank_weights="",
        symbol_candidates_min_quote_volume_usdt=0.0,
        symbol_candidates_exclude="",
        symbol_candidates_filter_min_notional=False,
        symbol_candidates_max_abs_change_pct=0.0,
        max_notional_usdt=10_000.0,
        position_sizing="fixed",
        strategy_size_pct=100.0,
        strategy_fast=10,
        strategy_slow=30,
        timeframe="1m",
    )
    picked = select_top_usdm_candidates(ex, s)  # type: ignore[arg-type]
    assert picked[0] == "TREND/USDT:USDT"


# --- funding metric (#5) ---


def test_funding_metric_parsing() -> None:
    assert parse_rank_metrics("funding_rate, abs_funding") == ["funding", "abs_funding"]


def test_select_by_abs_funding_prefers_crowded_symbol() -> None:
    markets = {
        "HOT/USDT:USDT": _mkt("HOT/USDT:USDT"),
        "COOL/USDT:USDT": _mkt("COOL/USDT:USDT"),
    }
    tickers = {
        "HOT/USDT:USDT": {"last": 1.0, "quoteVolume": 5e8, "percentage": 3.0},
        "COOL/USDT:USDT": {"last": 1.0, "quoteVolume": 9e8, "percentage": 1.0},
    }
    funding = {
        "HOT/USDT:USDT": {"fundingRate": 0.0009},
        "COOL/USDT:USDT": {"fundingRate": 0.0001},
    }
    ex = _FakeOhlcvEx(markets, tickers, {}, funding=funding)
    s = Settings.model_construct(
        symbol_mode="signal_pick",
        symbol_candidates="auto",
        symbol_candidates_count=2,
        symbol_candidates_rank_by="abs_funding",
        symbol_candidates_rank_weights="",
        symbol_candidates_min_quote_volume_usdt=0.0,
        symbol_candidates_exclude="",
        symbol_candidates_filter_min_notional=False,
        symbol_candidates_max_abs_change_pct=0.0,
        max_notional_usdt=10_000.0,
        position_sizing="fixed",
        strategy_size_pct=100.0,
    )
    picked = select_top_usdm_candidates(ex, s)  # type: ignore[arg-type]
    assert picked[0] == "HOT/USDT:USDT"


def test_funding_fetch_failure_degrades_gracefully() -> None:
    markets = {
        "AAA/USDT:USDT": _mkt("AAA/USDT:USDT"),
        "BBB/USDT:USDT": _mkt("BBB/USDT:USDT"),
    }
    tickers = {
        "AAA/USDT:USDT": {"last": 1.0, "quoteVolume": 9e8, "percentage": 3.0},
        "BBB/USDT:USDT": {"last": 1.0, "quoteVolume": 5e8, "percentage": 1.0},
    }

    class _NoFunding(_FakeOhlcvEx):
        def fetch_funding_rates(self) -> dict:
            raise RuntimeError("not supported")

    ex = _NoFunding(markets, tickers, {})
    s = Settings.model_construct(
        symbol_mode="signal_pick",
        symbol_candidates="auto",
        symbol_candidates_count=2,
        symbol_candidates_rank_by="abs_funding,liquidity",
        symbol_candidates_rank_weights="0.5,0.5",
        symbol_candidates_min_quote_volume_usdt=0.0,
        symbol_candidates_exclude="",
        symbol_candidates_filter_min_notional=False,
        symbol_candidates_max_abs_change_pct=0.0,
        max_notional_usdt=10_000.0,
        position_sizing="fixed",
        strategy_size_pct=100.0,
    )
    # funding 拉取失败 → 该指标降级，仍能按 liquidity 选出 2 个
    picked = select_top_usdm_candidates(ex, s)  # type: ignore[arg-type]
    assert len(picked) == 2
    assert picked[0] == "AAA/USDT:USDT"
