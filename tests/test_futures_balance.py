"""Tests for parsing Binance USDT-M balance fields."""

from __future__ import annotations

from futures_llm_bot.positions import fetch_futures_usdt_balance


class _BalEx:
    def __init__(self, bal: dict) -> None:
        self._bal = bal

    def fetch_balance(self) -> dict:
        return self._bal


def test_ccxt_usdt_free_and_total() -> None:
    ex = _BalEx({"USDT": {"total": 44.0, "free": 30.5, "used": 13.5}})
    total, available = fetch_futures_usdt_balance(ex)  # type: ignore[arg-type]
    assert total == 44.0
    assert available == 30.5


def test_fapi_assets_available_balance() -> None:
    ex = _BalEx(
        {
            "USDT": {"total": 100.0},
            "info": {
                "assets": [
                    {"asset": "USDT", "walletBalance": "100", "availableBalance": "72.25"},
                ]
            },
        }
    )
    total, available = fetch_futures_usdt_balance(ex)  # type: ignore[arg-type]
    assert total == 100.0
    assert available == 72.25
