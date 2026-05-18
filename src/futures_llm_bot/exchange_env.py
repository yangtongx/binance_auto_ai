"""Binance USDT-M environment: mainnet vs demo (replaces deprecated futures testnet sandbox)."""

from __future__ import annotations

import logging

import ccxt

logger = logging.getLogger(__name__)


def configure_binance_usdm_exchange(ex: ccxt.binanceusdm) -> None:
    """CCXT options for USDT-M only (no spot SAPI ``fetch_currencies`` on startup)."""
    ex.options = {**ex.options, "defaultType": "future", "fetchCurrencies": False}


def load_binance_usdm_markets(ex: ccxt.binanceusdm) -> None:
    """Load futures markets without calling spot wallet SAPI (futures-only API keys)."""
    configure_binance_usdm_exchange(ex)
    ex.load_markets()


def apply_binance_usdm_environment(ex: ccxt.binanceusdm, *, testnet: bool) -> None:
    """Configure exchange URLs for paper/demo vs mainnet.

    CCXT removed futures **sandbox** private APIs (``set_sandbox_mode`` on testnet URLs).
    When ``testnet=True``, enable **demo trading** (``demo-fapi.binance.com``) instead.
    Keys must be created at https://demo.binance.com (not mainnet keys).
    """
    configure_binance_usdm_exchange(ex)
    if not testnet:
        return
    enable_demo = getattr(ex, "enable_demo_trading", None)
    if callable(enable_demo):
        enable_demo(True)
        logger.info(
            "Binance USDM: demo trading enabled (demo-fapi); use futures API keys from demo.binance.com"
        )
        return
    logger.warning(
        "CCXT has no enable_demo_trading(); falling back to set_sandbox_mode — "
        "futures private API may raise NotSupported; upgrade ccxt>=4.4"
    )
    ex.set_sandbox_mode(True)


def binance_usdm_ws_base(*, testnet: bool) -> str:
    """Public kline WebSocket base (path appended by caller).

    Demo accounts use the same USDM market data feed as mainnet.
    """
    _ = testnet
    return "wss://fstream.binance.com/ws"
