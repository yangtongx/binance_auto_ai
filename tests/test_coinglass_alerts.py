"""Tests for CoinGlass alert parsing and watcher logic."""

from __future__ import annotations

from unittest.mock import patch

from binance_auto_ai.coinglass import (
    normalize_exchange_balance,
    normalize_spot_netflow,
    normalize_whale_transfer,
)
from binance_auto_ai.coinglass_alerts import CoinglassAlertWatcher, resolve_watch_coins
from binance_auto_ai.config import Settings


def test_normalize_spot_netflow() -> None:
    rows = [
        {
            "symbol": "BTC",
            "net_flow_usd_24h": -104_203_852.16,
            "net_flow_usd_1h": -12_000_000.0,
        },
        {"coin": "ETH", "netFlowUsd24h": 5_000_000.0},
    ]
    out = normalize_spot_netflow(rows)
    assert out["BTC"]["net_flow_24h_usd"] == -104_203_852.16
    assert out["BTC"]["net_flow_1h_usd"] == -12_000_000.0
    assert out["ETH"]["net_flow_24h_usd"] == 5_000_000.0


def test_normalize_exchange_balance() -> None:
    rows = [
        {
            "exchange_name": "Binance",
            "balance_change_percent_1d": 2.5,
            "balance_change_1d": 500.0,
            "total_balance": 582344.0,
        },
        {"exchangeName": "OKX", "balanceChangePercent1d": 0.5},
    ]
    out = normalize_exchange_balance(rows)
    assert out[0]["exchange_name"] == "Binance"
    assert out[0]["balance_change_percent_1d"] == 2.5
    assert out[1]["exchange_name"] == "OKX"
    assert out[1]["balance_change_percent_1d"] == 0.5


def test_normalize_whale_transfer() -> None:
    row = {
        "transaction_hash": "0xabc",
        "amount_usd": "18403606.87",
        "asset_symbol": "WETH",
        "from": "unknown wallet",
        "to": "Binance",
        "blockchain_name": "ethereum",
        "block_timestamp": 1746265043,
    }
    out = normalize_whale_transfer(row)
    assert out is not None
    assert out["transaction_hash"] == "0xabc"
    assert out["amount_usd"] == 18403606.87
    assert out["to"] == "Binance"


def test_resolve_watch_coins_merges_sources() -> None:
    coins = resolve_watch_coins(
        candidate_symbols=["DOGE/USDT:USDT", "SOL/USDT:USDT"],
        held_symbols=["ETH/USDT:USDT"],
        extra="BTC,DOGE",
    )
    assert coins == ["BTC", "DOGE", "ETH", "SOL"]


def _alert_settings(**kw: object) -> Settings:
    base = dict(
        coinglass_api_key="k",
        coinglass_alerts_on=True,
        telegram_notify_cg_alerts=True,
        telegram_bot_token="t",
        telegram_chat_id="c",
        coinglass_alert_interval_sec=60.0,
        coinglass_alert_cooldown_sec=0.0,
        coinglass_alert_netflow_usd=50_000_000.0,
        coinglass_alert_exchange_balance_pct_1d=0.0,
        coinglass_alert_whale_usd=0.0,
        coinglass_alert_extra_coins="",
    )
    base.update(kw)
    return Settings.model_construct(**base)


class _FakeCg:
    def __init__(self) -> None:
        self.netflow = {"DOGE": {"net_flow_24h_usd": -80_000_000.0, "net_flow_1h_usd": -5_000_000.0}}
        self.balance: dict[str, list] = {}
        self.whales: dict[str, list] = {}

    def spot_netflow(self) -> dict:
        return self.netflow

    def exchange_balance(self, coin: str) -> list:
        return self.balance.get(coin, [])

    def whale_transfers(self, coin: str, *, start_ms: int, end_ms: int) -> list:
        _ = start_ms, end_ms
        return self.whales.get(coin, [])


def test_alert_watcher_netflow_fires_once_per_cooldown() -> None:
    watcher = CoinglassAlertWatcher()
    cg = _FakeCg()
    settings = _alert_settings()
    with patch("binance_auto_ai.coinglass_alerts.notify_coinglass_alert") as notify:
        watcher.maybe_check(settings, cg, candidate_symbols=["DOGE/USDT:USDT"], held_symbols=[])
        assert notify.call_count == 1
        text = notify.call_args[0][1]
        assert "DOGE" in text
        assert "净流出" in text
        watcher.maybe_check(settings, cg, candidate_symbols=["DOGE/USDT:USDT"], held_symbols=[])
        assert notify.call_count == 1


def test_alert_watcher_exchange_balance() -> None:
    watcher = CoinglassAlertWatcher()
    cg = _FakeCg()
    cg.balance["BTC"] = [
        {"exchange_name": "Binance", "balance_change_percent_1d": 3.0},
        {"exchange_name": "OKX", "balance_change_percent_1d": 1.0},
    ]
    settings = _alert_settings(
        coinglass_alert_netflow_usd=0.0,
        coinglass_alert_exchange_balance_pct_1d=2.0,
    )
    with patch("binance_auto_ai.coinglass_alerts.notify_coinglass_alert") as notify:
        watcher.maybe_check(settings, cg, candidate_symbols=[], held_symbols=[], )
        # need BTC in watch list
        watcher._last_run_monotonic = 0.0
        watcher.maybe_check(settings, cg, candidate_symbols=["BTC/USDT:USDT"], held_symbols=[])
        assert notify.call_count == 1
        assert "储备增加" in notify.call_args[0][1]


def test_coinglass_alert_enabled_requires_switch_and_threshold() -> None:
    s = _alert_settings(coinglass_alerts_on=False)
    assert s.coinglass_alert_enabled() is False
    s2 = _alert_settings(coinglass_alert_netflow_usd=0.0, coinglass_alert_whale_usd=0.0)
    assert s2.coinglass_alert_enabled() is False
