from __future__ import annotations

from unittest.mock import MagicMock

from binance_auto_ai.config import Settings
from binance_auto_ai.symbol_universe import select_top_usdm_candidates


def _ticker(pct: float, qv: float, last: float = 1.0) -> dict[str, object]:
    return {
        "percentage": pct,
        "quoteVolume": qv,
        "last": last,
        "info": {"openInterest": 0},
    }


def test_pump_filter_drops_pump_and_dump_symbols() -> None:
    markets = {
        f"{s}/USDT:USDT": {"symbol": f"{s}/USDT:USDT", "quote": "USDT", "swap": True, "active": True}
        for s in ("CALM", "PUMP", "DUMP", "SOL", "DOGE")
    }
    tickers = {
        "CALM/USDT:USDT": _ticker(2.5, 50_000_000),
        "PUMP/USDT:USDT": _ticker(180.0, 80_000_000),
        "DUMP/USDT:USDT": _ticker(-95.0, 30_000_000),
        "SOL/USDT:USDT": _ticker(3.0, 5_000_000_000),
        "DOGE/USDT:USDT": _ticker(1.5, 2_000_000_000),
    }
    ex = MagicMock()
    ex.markets = markets
    ex.fetch_tickers.return_value = tickers

    s = Settings(
        symbol_candidates="auto",
        symbol_candidates_count=5,
        symbol_candidates_rank_by="liquidity,abs_change",
        symbol_candidates_rank_weights="0.7,0.3",
        symbol_candidates_min_quote_volume_usdt=1_000_000,
        symbol_candidates_exclude="BTC/USDT:USDT,ETH/USDT:USDT",
        symbol_candidates_filter_min_notional=False,
        symbol_candidates_max_abs_change_pct=30.0,
    )
    picked = select_top_usdm_candidates(ex, s, equity_usdt=100.0, available_margin_usdt=100.0)
    assert "PUMP/USDT:USDT" not in picked
    assert "DUMP/USDT:USDT" not in picked
    assert "SOL/USDT:USDT" in picked
    assert "DOGE/USDT:USDT" in picked
    assert "CALM/USDT:USDT" in picked


def test_pump_filter_off_keeps_movers() -> None:
    markets = {
        "PUMP/USDT:USDT": {"symbol": "PUMP/USDT:USDT", "quote": "USDT", "swap": True, "active": True},
        "SOL/USDT:USDT": {"symbol": "SOL/USDT:USDT", "quote": "USDT", "swap": True, "active": True},
    }
    tickers = {
        "PUMP/USDT:USDT": _ticker(180.0, 100_000_000),
        "SOL/USDT:USDT": _ticker(2.0, 200_000_000),
    }
    ex = MagicMock()
    ex.markets = markets
    ex.fetch_tickers.return_value = tickers
    s = Settings(
        symbol_candidates="auto",
        symbol_candidates_count=5,
        symbol_candidates_min_quote_volume_usdt=1_000_000,
        symbol_candidates_exclude="BTC/USDT:USDT,ETH/USDT:USDT",
        symbol_candidates_filter_min_notional=False,
        symbol_candidates_max_abs_change_pct=0.0,
    )
    picked = select_top_usdm_candidates(ex, s, equity_usdt=100.0, available_margin_usdt=100.0)
    assert "PUMP/USDT:USDT" in picked
