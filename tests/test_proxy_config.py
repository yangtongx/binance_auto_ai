from __future__ import annotations

from binance_auto_ai.config import Settings
from binance_auto_ai.exchange_env import ccxt_proxies, normalize_proxy_url, resolve_binance_proxy


def test_socks5_normalized_to_socks5h() -> None:
    assert normalize_proxy_url("socks5://127.0.0.1:1080") == "socks5h://127.0.0.1:1080"


def test_ccxt_proxies() -> None:
    assert ccxt_proxies(None) is None
    assert ccxt_proxies("http://127.0.0.1:7890") == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }


def test_resolve_proxy_from_settings(monkeypatch) -> None:
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    s = Settings.model_construct(binance_https_proxy="http://127.0.0.1:1080")
    assert resolve_binance_proxy(s) == "http://127.0.0.1:1080"
