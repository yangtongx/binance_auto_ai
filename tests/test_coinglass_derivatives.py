from __future__ import annotations

from binance_auto_ai.coinglass_derivatives import (
    build_market_context,
    derivatives_exit_reason,
    latest_history_row,
    parse_top_account_ratio,
    rank_metrics_from_context,
    summarize_liquidation_heatmap,
    summarize_liquidation_map,
    symbol_to_coinglass_pair,
)
from binance_auto_ai.config import Settings


def test_symbol_to_coinglass_pair() -> None:
    assert symbol_to_coinglass_pair("ZEC/USDT:USDT") == "ZECUSDT"


def test_latest_history_row_picks_max_time() -> None:
    rows = [
        {"time": 1000, "top_account_long_percent": 60.0},
        {"time": 2000, "top_account_long_percent": 70.0},
    ]
    row = latest_history_row(rows)
    assert row is not None
    assert row["top_account_long_percent"] == 70.0


def test_parse_top_account_ratio() -> None:
    parsed = parse_top_account_ratio(
        {
            "top_account_long_percent": 73.3,
            "top_account_short_percent": 26.7,
            "top_account_long_short_ratio": 2.75,
        }
    )
    assert parsed["top_account_long_pct"] == 73.3
    assert parsed["top_account_ratio"] == 2.75


def test_summarize_liquidation_heatmap() -> None:
    data = {
        "data": {
            "y_axis": [90.0, 100.0, 110.0],
            "liquidation_leverage_data": [
                [0, 0, 800_000.0],
                [0, 2, 1_500_000.0],
            ],
        }
    }
    s = summarize_liquidation_heatmap(data, mark_price=100.0)
    assert s["liq_heatmap_below_usd"] == 800_000.0
    assert s["liq_heatmap_above_usd"] == 1_500_000.0
    assert s["liq_heatmap_nearest_long_price"] == 90.0
    assert s["liq_heatmap_nearest_short_price"] == 110.0


def test_summarize_liquidation_map() -> None:
    data = {
        "data": {
            "90": [[90, 1_000_000.0, None, None]],
            "110": [[110, 2_000_000.0, None, None]],
        }
    }
    s = summarize_liquidation_map(data, mark_price=100.0)
    assert s["liq_notional_below_mark_usd"] == 1_000_000.0
    assert s["liq_notional_above_mark_usd"] == 2_000_000.0
    assert s["liq_nearest_long_price"] == 90.0
    assert s["liq_nearest_short_price"] == 110.0


def test_build_market_context() -> None:
    ctx = build_market_context(
        symbol="BTC/USDT:USDT",
        mark_price=100_000.0,
        top_account_row={"top_account_long_percent": 60, "top_account_short_percent": 40, "top_account_long_short_ratio": 1.5},
        top_position_row=None,
        global_account_row=None,
        net_position_row={"net_long_change_cum": 10, "net_short_change_cum": -5, "net_position_change_cum": 5},
        liq_summary=None,
    )
    assert ctx.coin == "BTC"
    assert ctx.top_account_long_pct == 60.0
    assert ctx.net_position_change_cum == 5.0


def test_rank_metrics_from_context() -> None:
    ctx = build_market_context(
        symbol="ETH/USDT:USDT",
        mark_price=3000.0,
        top_account_row={"top_account_long_percent": 80, "top_account_short_percent": 20, "top_account_long_short_ratio": 4},
        top_position_row={"top_position_long_percent": 70, "top_position_short_percent": 30, "top_position_long_short_ratio": 2.3},
        global_account_row={"global_account_long_percent": 60, "global_account_short_percent": 40, "global_account_long_short_ratio": 1.5},
        net_position_row={"net_position_change_cum": 12.5},
        liq_summary={"liq_notional_below_mark_usd": 1e6, "liq_notional_above_mark_usd": 2e6},
    )
    m = rank_metrics_from_context(ctx)
    assert m["cg_top_account_long"] == 80.0
    assert m["cg_net_position"] == 12.5
    assert m["cg_liq_above"] == 2e6


def test_derivatives_exit_crowd_long() -> None:
    s = Settings.model_construct(
        exit_cg_top_account_crowd_pct=75.0,
        coinglass_derivatives_on=True,
        coinglass_api_key="k",
    )
    ctx = build_market_context(
        symbol="BTC/USDT:USDT",
        mark_price=100.0,
        top_account_row={"top_account_long_percent": 80, "top_account_short_percent": 20, "top_account_long_short_ratio": 4},
        top_position_row=None,
        global_account_row=None,
        net_position_row=None,
        liq_summary=None,
    )
    reason = derivatives_exit_reason("long", mark=100.0, settings=s, ctx=ctx)
    assert reason is not None
    assert "cg_crowd_top_account" in reason


def test_derivatives_exit_liq_cluster_short() -> None:
    s = Settings.model_construct(
        exit_cg_liq_cluster_usd=500_000.0,
        exit_cg_liq_cluster_dist_pct=2.0,
        coinglass_derivatives_on=True,
        coinglass_api_key="k",
    )
    ctx = build_market_context(
        symbol="BTC/USDT:USDT",
        mark_price=100.0,
        top_account_row=None,
        top_position_row=None,
        global_account_row=None,
        net_position_row=None,
        liq_summary={
            "liq_notional_above_mark_usd": 1_000_000.0,
            "liq_nearest_short_price": 101.0,
        },
    )
    reason = derivatives_exit_reason("short", mark=100.0, settings=s, ctx=ctx)
    assert reason is not None
    assert "cg_liq_cluster" in reason
