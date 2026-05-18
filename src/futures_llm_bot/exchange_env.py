"""Binance USDT-M environment: mainnet vs demo (replaces deprecated futures testnet sandbox)."""

from __future__ import annotations

import logging

import ccxt

logger = logging.getLogger(__name__)


def apply_binance_usdm_environment(ex: ccxt.binanceusdm, *, testnet: bool) -> None:
    """Configure exchange URLs for paper/demo vs mainnet.

    CCXT removed futures **sandbox** private APIs (``set_sandbox_mode`` on testnet URLs).
    When ``testnet=True``, enable **demo trading** (``demo-fapi.binance.com``) instead.
    Keys must be created at https://demo.binance.com (not mainnet keys).
    """
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
