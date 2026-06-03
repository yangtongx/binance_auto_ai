"""将 CoinGlass 衍生品快照写入日志与监控面板。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from binance_auto_ai import dashboard_state
from binance_auto_ai.coinglass_derivatives import format_market_context
from binance_auto_ai.config import Settings
from binance_auto_ai.positions import mark_last_usdt

if TYPE_CHECKING:
    from binance_auto_ai.coinglass import CoinglassClient

logger = logging.getLogger(__name__)


def refresh_coinglass_market_views(
    ex,
    coinglass: CoinglassClient | None,
    settings: Settings,
    symbols: list[str],
) -> None:
    """对给定交易对拉取多空比/净多空/清算地图并记录（失败静默）。"""
    if coinglass is None or not settings.coinglass_derivatives_enabled():
        return
    seen: set[str] = set()
    for sym in symbols:
        if not sym or sym in seen:
            continue
        seen.add(sym)
        mark: float | None = None
        try:
            mark = mark_last_usdt(ex, sym)
        except Exception as e:  # noqa: BLE001
            logger.debug("mark price for %s failed: %s", sym, e)
        ctx = coinglass.market_context(sym, mark_price=mark)
        if ctx is None:
            continue
        dashboard_state.set_cg_market(sym, ctx.to_dict())
        logger.info("CoinGlass market context (%s):\n%s", sym, format_market_context(ctx))


def coinglass_llm_appendix(
    coinglass: CoinglassClient | None,
    settings: Settings,
    symbol: str,
    *,
    mark_price: float | None = None,
) -> str:
    if coinglass is None or not settings.coinglass_derivatives_enabled():
        return ""
    ctx = coinglass.market_context(symbol, mark_price=mark_price)
    if ctx is None:
        return ""
    return "\n\nCoinGlass derivatives context:\n" + format_market_context(ctx)
