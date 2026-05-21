"""币安 USDT-M 环境：主网/演示盘、代理、加载市场、设置杠杆。"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import ccxt

if TYPE_CHECKING:
    from futures_llm_bot.config import Settings

logger = logging.getLogger(__name__)


def resolve_binance_proxy(settings: Settings) -> str | None:
    """Proxy URL for CCXT/requests (local Clash/SSR). Empty = direct connection."""
    explicit = (settings.binance_https_proxy or "").strip()
    if explicit:
        return explicit
    for key in ("BINANCE_HTTPS_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return None


def normalize_proxy_url(proxy_url: str) -> str:
    """``socks5h`` resolves DNS via proxy; fixes many SSR/Clash + Binance SSL EOF errors."""
    u = proxy_url.strip()
    if u.startswith("socks5://"):
        return "socks5h://" + u[len("socks5://") :]
    return u


def ccxt_proxies(proxy_url: str | None) -> dict[str, str] | None:
    if not proxy_url:
        return None
    u = normalize_proxy_url(proxy_url)
    return {"http": u, "https": u}


def apply_ccxt_proxy_config(settings: Settings, cfg: dict) -> None:
    proxy = resolve_binance_proxy(settings)
    proxies = ccxt_proxies(proxy)
    if proxies:
        cfg["proxies"] = proxies
        logger.info("Binance CCXT proxy: %s", proxies["https"])


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
        logger.info("Binance USDM: mainnet (fapi.binance.com); use API keys from binance.com")
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


def apply_symbol_leverage(ex: ccxt.binanceusdm, settings: Settings, *, symbol: str | None = None) -> None:
    """Set isolated/cross leverage on the traded symbol (mainnet keys required)."""
    sym = symbol or settings.symbol
    if settings.leverage <= 1.0:
        return
    if not settings.binance_api_key or settings.dry_run:
        logger.info(
            "skip set_leverage(%.0f) on %s (dry_run=%s or no API key)",
            settings.leverage,
            sym,
            settings.dry_run,
        )
        return
    lev = int(round(settings.leverage))
    try:
        ex.set_leverage(lev, sym)
        logger.info("Binance USDM leverage set to %sx on %s", lev, sym)
    except ccxt.BaseError as e:
        logger.warning("set_leverage(%s, %s) failed: %s", lev, sym, e)


def apply_candidates_leverage(ex: ccxt.binanceusdm, settings: Settings) -> None:
    for sym in settings.candidate_symbols():
        apply_symbol_leverage(ex, settings, symbol=sym)


def binance_usdm_ws_base(*, testnet: bool) -> str:
    """Public kline WebSocket base (path appended by caller).

    Demo accounts use the same USDM market data feed as mainnet.
    """
    _ = testnet
    return "wss://fstream.binance.com/ws"
