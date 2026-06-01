from __future__ import annotations

from binance_auto_ai.symbol_input import candidate_ccxt_symbols, resolve_usdm_symbol


class _FakeEx:
    def __init__(self, symbols: list[str]) -> None:
        self.markets = {s: {"active": True, "linear": True} for s in symbols}


def test_candidate_from_ticker() -> None:
    assert "DOGE/USDT:USDT" in candidate_ccxt_symbols("DOGE")
    assert "BTC/USDT:USDT" in candidate_ccxt_symbols("BTCUSDT")
    assert candidate_ccxt_symbols("ETH/USDT:USDT") == ["ETH/USDT:USDT"]


def test_resolve_on_exchange() -> None:
    ex = _FakeEx(["DOGE/USDT:USDT", "BTC/USDT:USDT"])
    assert resolve_usdm_symbol(ex, "doge") == "DOGE/USDT:USDT"
    assert resolve_usdm_symbol(ex, "BTC/USDT:USDT") == "BTC/USDT:USDT"
