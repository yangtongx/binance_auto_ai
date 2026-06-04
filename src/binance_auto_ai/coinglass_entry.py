"""CoinGlass 开仓过滤与 signal_pick 置信度加权（清算地图 + 热力图）。"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from binance_auto_ai.coinglass_derivatives import CoinGlassMarketContext
from binance_auto_ai.config import Settings
from binance_auto_ai.schemas import Action, LLMSignal

if TYPE_CHECKING:
    from binance_auto_ai.coinglass import CoinglassClient
    from binance_auto_ai.symbol_picker import SymbolPick

logger = logging.getLogger(__name__)


def entry_cg_enabled(settings: Settings) -> bool:
    return settings.coinglass_derivatives_enabled() and settings.entry_cg_on


def _combined_liq_below(ctx: CoinGlassMarketContext) -> float | None:
    vals = [ctx.liq_notional_below_mark_usd, ctx.liq_heatmap_below_usd]
    present = [v for v in vals if v is not None and v > 0]
    return max(present) if present else None


def _combined_liq_above(ctx: CoinGlassMarketContext) -> float | None:
    vals = [ctx.liq_notional_above_mark_usd, ctx.liq_heatmap_above_usd]
    present = [v for v in vals if v is not None and v > 0]
    return max(present) if present else None


def _liq_strength(usd: float | None, *, min_usd: float) -> float:
    if usd is None or usd < min_usd or min_usd <= 0:
        return 0.0
    # 10× 门槛附近趋近 1.0
    return min(1.0, math.log1p(usd / min_usd) / math.log1p(10.0))


def _dist_pct(mark: float, level: float | None) -> float | None:
    if mark <= 0 or level is None or level <= 0:
        return None
    return abs(mark - level) / mark * 100.0


def entry_cg_alignment(side: str, ctx: CoinGlassMarketContext | None, settings: Settings) -> float:
    """
    清算结构对齐度 [0,1]。无数据返回 0.5（中性）。

    做多：上方空头清算簇（磁吸上扫）加分；现价贴近下方多头清算簇减分。
    做空：对称。
    """
    if ctx is None or not entry_cg_enabled(settings):
        return 0.5
    mark = ctx.mark_price
    if mark is None or mark <= 0:
        return 0.5
    min_usd = float(settings.entry_cg_liq_min_usd)
    below = _combined_liq_below(ctx)
    above = _combined_liq_above(ctx)
    if side == "long":
        favorable = _liq_strength(above, min_usd=min_usd)
        against = _liq_strength(below, min_usd=min_usd)
        near = ctx.liq_nearest_long_price or ctx.liq_heatmap_nearest_long_price
    else:
        favorable = _liq_strength(below, min_usd=min_usd)
        against = _liq_strength(above, min_usd=min_usd)
        near = ctx.liq_nearest_short_price or ctx.liq_heatmap_nearest_short_price
    against_near = 0.0
    if against > 0:
        dist = _dist_pct(mark, near)
        block_dist = float(settings.entry_cg_block_dist_pct)
        if dist is not None and block_dist > 0 and dist <= block_dist:
            against_near = against * (1.0 - dist / block_dist)
    raw = favorable - 0.45 * against_near
    return max(0.0, min(1.0, 0.5 + 0.5 * raw))


def entry_cg_block_reason(
    side: str,
    ctx: CoinGlassMarketContext | None,
    settings: Settings,
) -> str | None:
    """逆势贴近危险清算簇时拒绝新开仓。"""
    if ctx is None or not entry_cg_enabled(settings) or not settings.entry_cg_block_against:
        return None
    mark = ctx.mark_price
    if mark is None or mark <= 0 or side not in ("long", "short"):
        return None
    min_usd = float(settings.entry_cg_liq_min_usd)
    dist_cap = float(settings.entry_cg_block_dist_pct)
    if min_usd <= 0 or dist_cap <= 0:
        return None
    if side == "long":
        against = _combined_liq_below(ctx)
        near = ctx.liq_nearest_long_price or ctx.liq_heatmap_nearest_long_price
        label = "below"
    else:
        against = _combined_liq_above(ctx)
        near = ctx.liq_nearest_short_price or ctx.liq_heatmap_nearest_short_price
        label = "above"
    if against is None or against < min_usd or near is None or near <= 0:
        return None
    dist = _dist_pct(mark, near)
    if dist is None or dist > dist_cap:
        return None
    return (
        f"cg_entry_block {side} {label}=${against:.0f} @ {near:.6g} "
        f"dist={dist:.2f}%<={dist_cap:.2f}%"
    )


def _directional_score(signal: LLMSignal, *, min_confidence: float) -> float | None:
    if signal.action not in (Action.LONG, Action.SHORT):
        return None
    if signal.confidence < min_confidence:
        return None
    return float(signal.confidence)


def blend_confidence_with_cg(
    confidence: float,
    side: str,
    ctx: CoinGlassMarketContext | None,
    settings: Settings,
) -> float:
    w = float(settings.entry_cg_weight) if entry_cg_enabled(settings) else 0.0
    if w <= 0.0:
        return confidence
    align = entry_cg_alignment(side, ctx, settings)
    return confidence * ((1.0 - w) + w * (0.5 + 0.5 * align))


def pick_score(
    sym: str,
    sig: LLMSignal,
    *,
    min_confidence: float,
    contexts: dict[str, CoinGlassMarketContext],
    settings: Settings,
) -> float | None:
    base = _directional_score(sig, min_confidence=min_confidence)
    if base is None:
        return None
    side = sig.action.value
    ctx = contexts.get(sym)
    block = entry_cg_block_reason(side, ctx, settings)
    if block:
        logger.info("signal_pick CoinGlass blocked %s: %s", sym, block)
        return None
    return blend_confidence_with_cg(base, side, ctx, settings)


def pick_best_with_coinglass(
    signals: dict[str, LLMSignal],
    *,
    candidates_order: list[str],
    min_confidence: float,
    contexts: dict[str, CoinGlassMarketContext],
    settings: Settings,
):
    from binance_auto_ai.symbol_picker import SymbolPick

    best: SymbolPick | None = None
    for sym in candidates_order:
        sig = signals.get(sym)
        if sig is None:
            continue
        score = pick_score(
            sym,
            sig,
            min_confidence=min_confidence,
            contexts=contexts,
            settings=settings,
        )
        if score is None:
            continue
        if best is None or score > best.score or (score == best.score and sym < best.symbol):
            best = SymbolPick(sym, sig, score)
    return best


def fetch_entry_contexts(
    ex,
    coinglass: CoinglassClient | None,
    settings: Settings,
    candidates: list[str],
    signals: dict[str, LLMSignal],
) -> dict[str, CoinGlassMarketContext]:
    """为达到 min_confidence 的方向信号拉取 CoinGlass 快照（含地图+热力图）。"""
    if coinglass is None or not entry_cg_enabled(settings):
        return {}
    from binance_auto_ai.positions import mark_last_usdt

    out: dict[str, CoinGlassMarketContext] = {}
    for sym in candidates:
        sig = signals.get(sym)
        if sig is None or sig.action not in (Action.LONG, Action.SHORT):
            continue
        if sig.confidence < settings.min_confidence:
            continue
        mark: float | None = None
        try:
            mark = mark_last_usdt(ex, sym)
        except Exception as e:  # noqa: BLE001
            logger.debug("entry cg mark for %s failed: %s", sym, e)
        ctx = coinglass.market_context(sym, mark_price=mark)
        if ctx is not None:
            out[sym] = ctx
    return out
