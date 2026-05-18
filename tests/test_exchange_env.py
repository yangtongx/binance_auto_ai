from __future__ import annotations

from unittest.mock import MagicMock

from futures_llm_bot.exchange_env import apply_binance_usdm_environment, binance_usdm_ws_base


def test_apply_demo_calls_enable_demo_trading() -> None:
    ex = MagicMock()
    ex.enable_demo_trading = MagicMock()
    apply_binance_usdm_environment(ex, testnet=True)
    ex.enable_demo_trading.assert_called_once_with(True)
    ex.set_sandbox_mode.assert_not_called()


def test_apply_mainnet_noop() -> None:
    ex = MagicMock()
    apply_binance_usdm_environment(ex, testnet=False)
    ex.enable_demo_trading.assert_not_called()
    ex.set_sandbox_mode.assert_not_called()


def test_ws_base_uses_mainnet_fstream() -> None:
    assert binance_usdm_ws_base(testnet=True).startswith("wss://fstream.binance.com")
