"""Integration-style tests against a minimal exchange stub (no network)."""

from __future__ import annotations

from typing import Any

import pytest

from futures_llm_bot.config import Settings
from futures_llm_bot.execution import execute_signal
from futures_llm_bot.schemas import Action, LLMSignal


class FakeUSDMM:
    """Duck-typed stub with only the CCXT surface this bot uses during execution."""

    def __init__(self, symbol: str = "BTC/USDT:USDT") -> None:
        self.symbol = symbol
        self._last = 50_000.0
        self._net = 0.0
        self.orders: list[dict[str, Any]] = []
        self.markets: dict[str, Any] = {}

    def load_markets(self) -> dict[str, Any]:
        self.markets = {
            self.symbol: {
                "symbol": self.symbol,
                "precision": {"amount": 3, "price": 2},
                "limits": {
                    "amount": {"min": 0.001},
                    "cost": {"min": 5.0},
                },
            }
        }
        return self.markets

    def market(self, symbol: str) -> dict[str, Any]:
        return self.markets[symbol]

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return {"last": self._last, "close": self._last}

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        _ = symbol
        return f"{round(amount, 3):.3f}"

    def fetch_positions(self, symbols: list[str]) -> list[dict[str, Any]]:
        if abs(self._net) < 1e-12 or symbols != [self.symbol]:
            return []
        side = "long" if self._net > 0 else "short"
        c = abs(self._net)
        n = c * self._last
        return [{"symbol": self.symbol, "side": side, "contracts": c, "notional": n}]

    def create_order(
        self,
        symbol: str,
        typ: str,
        side: str,
        amount: float,
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = typ, price
        params = params or {}
        amt = float(amount)
        ro = params.get("reduceOnly") in (True, "true", "True")
        self.orders.append({"symbol": symbol, "side": side, "amount": amt, "params": params})
        if ro:
            if side == "buy" and self._net < 0:
                self._net = min(0.0, self._net + amt)
            elif side == "sell" and self._net > 0:
                self._net = max(0.0, self._net - amt)
        else:
            if side == "buy":
                self._net += amt
            else:
                self._net -= amt
        return {"id": str(len(self.orders))}

    def fetch_ohlcv(self, *args: Any, **kwargs: Any) -> list[list[Any]]:
        _ = args, kwargs
        return []


@pytest.fixture
def exec_settings(tmp_path) -> Settings:
    return Settings.model_construct(
        symbol="BTC/USDT:USDT",
        max_notional_usdt=100.0,
        dry_run=False,
        position_poll_interval_sec=0.001,
        position_poll_timeout_sec=0.05,
        state_file=tmp_path / "session_state.json",
    )


def test_execute_oneway_long_submits_buy(exec_settings: Settings) -> None:
    ex = FakeUSDMM()
    ex.load_markets()
    sig = LLMSignal(action=Action.LONG, size_pct=100.0, confidence=0.9, reason="test")
    execute_signal(ex, exec_settings, sig, account_hedged=False, session=None)
    assert len(ex.orders) == 1
    assert ex.orders[0]["side"] == "buy"
    assert ex._net > 0


def test_execute_hold_no_orders(exec_settings: Settings) -> None:
    ex = FakeUSDMM()
    ex.load_markets()
    sig = LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=0.5, reason="test")
    execute_signal(ex, exec_settings, sig, account_hedged=False, session=None)
    assert ex.orders == []
