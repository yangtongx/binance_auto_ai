"""Tests for CoinGlass parsing and its selection-metric / funding-filter integration."""

from __future__ import annotations

from binance_auto_ai.coinglass import normalize_coin_metrics, normalize_exchange_balance, normalize_spot_netflow
from binance_auto_ai.config import Settings
from binance_auto_ai.symbol_universe import select_top_usdm_candidates


# --- pure parsing ---


def test_normalize_coin_metrics_field_variants() -> None:
    rows = [
        {"symbol": "BTC", "openInterestChangePercent24h": 5.0, "fundingRate": 0.01},
        {"coin": "ETH", "oiChangePercent24h": -3.0, "avgFundingRate": -0.02},
        {"baseAsset": "SOL", "openInterestChangePercent": 12.0},  # no funding
        {"nope": 1},  # no symbol -> skipped
    ]
    out = normalize_coin_metrics(rows)
    assert out["BTC"]["oi_change_pct"] == 5.0
    assert out["BTC"]["funding_rate"] == 0.01
    assert out["ETH"]["oi_change_pct"] == -3.0
    assert out["ETH"]["funding_rate"] == -0.02
    assert out["SOL"]["oi_change_pct"] == 12.0
    assert out["SOL"]["funding_rate"] is None
    assert len(out) == 3


def test_normalize_coin_metrics_substring_fallback() -> None:
    rows = [{"symbol": "DOGE", "h24OpenInterestChangePercent": 7.5, "lastFundingRateValue": 0.03}]
    out = normalize_coin_metrics(rows)
    assert out["DOGE"]["oi_change_pct"] == 7.5


def test_normalize_spot_netflow_and_exchange_balance() -> None:
    nf = normalize_spot_netflow([{"symbol": "BTC", "net_flow_usd_24h": -1e8}])
    assert nf["BTC"]["net_flow_24h_usd"] == -1e8
    bal = normalize_exchange_balance([{"exchange_name": "Binance", "balance_change_percent_1d": 1.2}])
    assert bal[0]["balance_change_percent_1d"] == 1.2


# --- selection integration ---


class _FakeEx:
    def __init__(self, markets: dict, tickers: dict) -> None:
        self.markets = markets
        self._tickers = tickers

    def fetch_tickers(self) -> dict:
        return self._tickers

    def market(self, symbol: str) -> dict:
        return self.markets[symbol]


class _FakeCg:
    def __init__(self, metrics: dict) -> None:
        self._m = metrics

    def coin_metrics(self) -> dict:
        return self._m


def _mkt(sym: str) -> dict:
    return {
        "symbol": sym,
        "quote": "USDT",
        "swap": True,
        "active": True,
        "limits": {"amount": {"min": 1.0}},
        "precision": {"amount": 1.0},
    }


def _base_settings(**kw: object) -> Settings:
    base = dict(
        symbol_mode="signal_pick",
        symbol_candidates="auto",
        symbol_candidates_count=2,
        symbol_candidates_rank_weights="",
        symbol_candidates_min_quote_volume_usdt=0.0,
        symbol_candidates_exclude="",
        symbol_candidates_filter_min_notional=False,
        symbol_candidates_max_abs_change_pct=0.0,
        max_notional_usdt=10_000.0,
        position_sizing="fixed",
        strategy_size_pct=100.0,
        leverage_mode="fixed",
        leverage=1.0,
        coinglass_api_key="k",
        coinglass_max_abs_funding_pct=0.0,
    )
    base.update(kw)
    return Settings.model_construct(**base)


def test_select_by_cg_oi_change_prefers_oi_growth() -> None:
    markets = {f"{c}/USDT:USDT": _mkt(f"{c}/USDT:USDT") for c in ("AAA", "BBB", "CCC")}
    tickers = {
        "AAA/USDT:USDT": {"last": 1.0, "quoteVolume": 5e8, "percentage": 2.0},
        "BBB/USDT:USDT": {"last": 1.0, "quoteVolume": 9e8, "percentage": 1.0},
        "CCC/USDT:USDT": {"last": 1.0, "quoteVolume": 7e8, "percentage": 3.0},
    }
    cg = _FakeCg(
        {
            "AAA": {"oi_change_pct": 80.0, "funding_rate": 0.0},
            "BBB": {"oi_change_pct": 10.0, "funding_rate": 0.0},
            "CCC": {"oi_change_pct": -20.0, "funding_rate": 0.0},
        }
    )
    s = _base_settings(symbol_candidates_rank_by="cg_oi_change")
    picked = select_top_usdm_candidates(_FakeEx(markets, tickers), s, coinglass=cg)  # type: ignore[arg-type]
    assert picked[0] == "AAA/USDT:USDT"  # highest OI growth


def test_funding_filter_excludes_crowded() -> None:
    markets = {f"{c}/USDT:USDT": _mkt(f"{c}/USDT:USDT") for c in ("AAA", "BBB", "CCC")}
    tickers = {
        "AAA/USDT:USDT": {"last": 1.0, "quoteVolume": 9e8, "percentage": 2.0},
        "BBB/USDT:USDT": {"last": 1.0, "quoteVolume": 5e8, "percentage": 1.0},
        "CCC/USDT:USDT": {"last": 1.0, "quoteVolume": 3e8, "percentage": 3.0},
    }
    cg = _FakeCg(
        {
            "AAA": {"oi_change_pct": None, "funding_rate": 0.2},  # crowded -> excluded
            "BBB": {"oi_change_pct": None, "funding_rate": 0.01},
            "CCC": {"oi_change_pct": None, "funding_rate": -0.01},
        }
    )
    s = _base_settings(
        symbol_candidates_rank_by="liquidity",
        symbol_candidates_count=5,
        coinglass_max_abs_funding_pct=0.05,
    )
    picked = select_top_usdm_candidates(_FakeEx(markets, tickers), s, coinglass=cg)  # type: ignore[arg-type]
    assert "AAA/USDT:USDT" not in picked
    assert "BBB/USDT:USDT" in picked
    assert "CCC/USDT:USDT" in picked


def test_cg_metric_degrades_when_key_missing() -> None:
    # key empty -> cg metric coverage 0 -> dropped, still ranks by liquidity
    markets = {f"{c}/USDT:USDT": _mkt(f"{c}/USDT:USDT") for c in ("AAA", "BBB")}
    tickers = {
        "AAA/USDT:USDT": {"last": 1.0, "quoteVolume": 9e8, "percentage": 2.0},
        "BBB/USDT:USDT": {"last": 1.0, "quoteVolume": 5e8, "percentage": 1.0},
    }
    s = _base_settings(symbol_candidates_rank_by="cg_oi_change,liquidity", coinglass_api_key="")
    picked = select_top_usdm_candidates(_FakeEx(markets, tickers), s)  # type: ignore[arg-type]
    assert len(picked) == 2
    assert picked[0] == "AAA/USDT:USDT"
