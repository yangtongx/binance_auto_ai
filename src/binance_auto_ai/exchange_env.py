"""币安 USDT-M 环境：主网/演示盘、代理、加载市场、设置杠杆。"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import ccxt

if TYPE_CHECKING:
    from binance_auto_ai.config import Settings

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
    try:
        ex.load_markets()
    except ccxt.ExchangeNotAvailable as e:
        raise _binance_connect_error(e) from e


def _binance_connect_error(exc: ccxt.ExchangeNotAvailable) -> SystemExit:
    """451 / 地区限制时给出可操作的退出提示。"""
    msg = str(exc)
    low = msg.lower()
    if "451" in msg or "restricted location" in low:
        return SystemExit(
            "Binance 451：当前出口 IP 所在地区被 Binance 拒绝（主网/模拟盘均可能触发）。\n"
            "解决：\n"
            "  1) 在 .env 设置 BINANCE_HTTPS_PROXY（Docker 访问宿主机 Clash：\n"
            "     BINANCE_HTTPS_PROXY=http://host.docker.internal:7890\n"
            "     需 docker-compose 已配置 extra_hosts: host.docker.internal:host-gateway）\n"
            "  2) 或使用容器/服务器可直接访问的远程 HTTP/SOCKS 代理 URL\n"
            "  3) 或将 VPS 换到 Binance 可访问地区\n"
            f"原始错误: {msg[:500]}"
        )
    return SystemExit(f"无法连接 Binance USDT-M: {msg[:500]}")


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


# 每个交易对的最大可用杠杆缓存（避免重复查询交易所）
_MAX_LEVERAGE_CACHE: dict[str, float] = {}
_LEVERAGE_TIER_CACHE: dict[str, list[dict]] = {}


def _tier_leverage(tier: dict) -> float | None:
    for key in ("maxLeverage", "initialLeverage", "max_leverage", "initial_leverage"):
        raw = tier.get(key)
        if raw is None:
            continue
        try:
            v = float(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def _tier_notional_cap(tier: dict) -> float | None:
    for key in ("maxNotional", "notionalCap", "max_notional", "notional_cap"):
        raw = tier.get(key)
        if raw is None:
            continue
        try:
            v = float(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def fetch_symbol_leverage_tiers(ex: ccxt.binanceusdm, symbol: str) -> list[dict]:
    """拉取并缓存该 symbol 的杠杆分层（需 API；失败返回空）。"""
    if symbol in _LEVERAGE_TIER_CACHE:
        return _LEVERAGE_TIER_CACHE[symbol]
    rows: list[dict] = []
    try:
        data = ex.fetch_leverage_tiers([symbol])
        raw = (data or {}).get(symbol) or []
        rows = [r for r in raw if isinstance(r, dict)]
    except Exception as e:  # noqa: BLE001
        logger.debug("fetch_leverage_tiers failed for %s: %s", symbol, e)
    _LEVERAGE_TIER_CACHE[symbol] = rows
    return rows


def symbol_max_notional_at_leverage(ex: ccxt.binanceusdm, symbol: str, leverage: float) -> float | None:
    """当前杠杆档位下该 symbol 允许的最大持仓名义（USDT）；用于避免 Binance -2027。"""
    if leverage <= 0:
        return None
    tiers = fetch_symbol_leverage_tiers(ex, symbol)
    if not tiers:
        return None
    lev = float(leverage)
    exact: float | None = None
    candidates: list[tuple[float, float]] = []
    for tier in tiers:
        ml = _tier_leverage(tier)
        cap = _tier_notional_cap(tier)
        if ml is None or cap is None:
            continue
        if abs(ml - lev) < 0.51:
            exact = cap
            break
        if ml >= lev - 0.5:
            candidates.append((ml, cap))
    if exact is not None:
        return exact
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def symbol_max_leverage(ex: ccxt.binanceusdm, symbol: str) -> float | None:
    """该交易对在币安允许的最大杠杆；先看市场 limits，再退回杠杆分层（需 API）。取不到返回 None。"""
    cached = _MAX_LEVERAGE_CACHE.get(symbol)
    if cached is not None:
        return cached
    max_lev: float | None = None
    try:
        market = ex.market(symbol)
    except Exception:  # noqa: BLE001
        market = None
    if isinstance(market, dict):
        lev_limits = (market.get("limits") or {}).get("leverage") or {}
        raw = lev_limits.get("max")
        try:
            if raw is not None and float(raw) > 0:
                max_lev = float(raw)
        except (TypeError, ValueError):
            max_lev = None
    if max_lev is None:
        try:
            tiers = fetch_symbol_leverage_tiers(ex, symbol)
            cand = max((_tier_leverage(t) or 0.0 for t in tiers), default=0.0)
            if cand > 0:
                max_lev = cand
        except Exception as e:  # noqa: BLE001 - 无 API/不支持时优雅降级
            logger.debug("leverage tiers max for %s failed: %s", symbol, e)
    if max_lev is not None:
        _MAX_LEVERAGE_CACHE[symbol] = max_lev
    return max_lev


def effective_leverage(ex: ccxt.binanceusdm, settings: Settings, symbol: str) -> float:
    """LEVERAGE_MODE=max 时取该币最大杠杆（取不到回退 LEVERAGE）；否则用固定 LEVERAGE。"""
    if settings.leverage_mode == "max":
        m = symbol_max_leverage(ex, symbol)
        if m is not None and m > 0:
            return m
        logger.warning(
            "max leverage unavailable for %s; falling back to LEVERAGE=%s", symbol, settings.leverage
        )
    return settings.leverage


def apply_symbol_leverage(ex: ccxt.binanceusdm, settings: Settings, *, symbol: str | None = None) -> None:
    """Set isolated/cross leverage on the traded symbol (mainnet keys required)."""
    sym = symbol or settings.symbol
    target = effective_leverage(ex, settings, sym)
    if target <= 1.0:
        return
    if not settings.binance_api_key or settings.dry_run:
        logger.info(
            "skip set_leverage(%.0f) on %s (dry_run=%s or no API key, mode=%s)",
            target,
            sym,
            settings.dry_run,
            settings.leverage_mode,
        )
        return
    lev = int(round(target))
    try:
        ex.set_leverage(lev, sym)
        logger.info("Binance USDM leverage set to %sx on %s (mode=%s)", lev, sym, settings.leverage_mode)
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
