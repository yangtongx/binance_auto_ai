"""CoinGlass 衍生品微观结构：清算地图、大户/全局多空比、净多空（解析 + 文案，供客户端调用）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def symbol_to_coinglass_pair(ccxt_symbol: str) -> str:
    """``BTC/USDT:USDT`` → ``BTCUSDT``。"""
    base = ccxt_symbol.split(":", 1)[0]
    return base.replace("/", "").upper()


def symbol_to_coinglass_coin(ccxt_symbol: str) -> str:
    pair = symbol_to_coinglass_pair(ccxt_symbol)
    if pair.endswith("USDT"):
        return pair[:-4]
    return pair


def coinglass_interval_from_timeframe(timeframe: str, *, fallback: str = "5m") -> str:
    tf = (timeframe or "").strip().lower()
    allowed = {
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "6h",
        "8h",
        "12h",
        "1d",
        "1w",
    }
    return tf if tf in allowed else fallback


def _as_float(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        if k in row:
            f = _as_float(row[k])
            if f is not None:
                return f
    return None


def latest_history_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    best = rows[0]
    best_t = _as_float(best.get("time")) or 0.0
    for row in rows[1:]:
        t = _as_float(row.get("time")) or 0.0
        if t >= best_t:
            best, best_t = row, t
    return best


def parse_top_account_ratio(row: dict[str, Any]) -> dict[str, float | None]:
    return {
        "top_account_long_pct": _pick(
            row,
            ("top_account_long_percent", "topAccountLongPercent", "longAccountPercent"),
        ),
        "top_account_short_pct": _pick(
            row,
            ("top_account_short_percent", "topAccountShortPercent", "shortAccountPercent"),
        ),
        "top_account_ratio": _pick(
            row,
            ("top_account_long_short_ratio", "topAccountLongShortRatio", "longShortRatio"),
        ),
    }


def parse_top_position_ratio(row: dict[str, Any]) -> dict[str, float | None]:
    return {
        "top_position_long_pct": _pick(
            row,
            ("top_position_long_percent", "topPositionLongPercent"),
        ),
        "top_position_short_pct": _pick(
            row,
            ("top_position_short_percent", "topPositionShortPercent"),
        ),
        "top_position_ratio": _pick(
            row,
            ("top_position_long_short_ratio", "topPositionLongShortRatio"),
        ),
    }


def parse_global_account_ratio(row: dict[str, Any]) -> dict[str, float | None]:
    return {
        "global_account_long_pct": _pick(
            row,
            ("global_account_long_percent", "globalAccountLongPercent"),
        ),
        "global_account_short_pct": _pick(
            row,
            ("global_account_short_percent", "globalAccountShortPercent"),
        ),
        "global_account_ratio": _pick(
            row,
            ("global_account_long_short_ratio", "globalAccountLongShortRatio"),
        ),
    }


def parse_net_position(row: dict[str, Any]) -> dict[str, float | None]:
    return {
        "net_long_change": _pick(row, ("net_long_change", "netLongChange")),
        "net_short_change": _pick(row, ("net_short_change", "netShortChange")),
        "net_long_change_cum": _pick(row, ("net_long_change_cum", "netLongChangeCum")),
        "net_short_change_cum": _pick(row, ("net_short_change_cum", "netShortChangeCum")),
        "net_position_change_cum": _pick(row, ("net_position_change_cum", "netPositionChangeCum")),
    }


def _liq_map_inner(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    inner = data.get("data", data)
    if isinstance(inner, dict) and isinstance(inner.get("data"), dict):
        inner = inner["data"]
    return inner if isinstance(inner, dict) else {}


def summarize_liquidation_map(
    data: Any,
    *,
    mark_price: float,
) -> dict[str, float | None]:
    """聚合清算地图：现价下方=多头清算簇（价跌触发），上方=空头清算簇。"""
    if mark_price <= 0:
        return {
            "liq_notional_below_mark_usd": None,
            "liq_notional_above_mark_usd": None,
            "liq_nearest_long_price": None,
            "liq_nearest_short_price": None,
        }
    inner = _liq_map_inner(data)
    below = 0.0
    above = 0.0
    nearest_long: float | None = None
    nearest_short: float | None = None
    for key, buckets in inner.items():
        price = _as_float(key)
        if price is None:
            continue
        if not isinstance(buckets, list):
            continue
        level_sum = 0.0
        for bucket in buckets:
            if not isinstance(bucket, (list, tuple)) or len(bucket) < 2:
                continue
            lv = _as_float(bucket[1])
            if lv is not None:
                level_sum += lv
        if level_sum <= 0:
            continue
        if price < mark_price:
            below += level_sum
            if nearest_long is None or price > nearest_long:
                nearest_long = price
        elif price > mark_price:
            above += level_sum
            if nearest_short is None or price < nearest_short:
                nearest_short = price
    return {
        "liq_notional_below_mark_usd": below if below > 0 else None,
        "liq_notional_above_mark_usd": above if above > 0 else None,
        "liq_nearest_long_price": nearest_long,
        "liq_nearest_short_price": nearest_short,
    }


@dataclass(frozen=True)
class CoinGlassMarketContext:
    """单币 CoinGlass 衍生品快照（最新一根多空比 + 可选清算地图摘要）。"""

    symbol: str
    coin: str
    pair: str
    mark_price: float | None = None
    top_account_long_pct: float | None = None
    top_account_short_pct: float | None = None
    top_account_ratio: float | None = None
    top_position_long_pct: float | None = None
    top_position_short_pct: float | None = None
    top_position_ratio: float | None = None
    global_account_long_pct: float | None = None
    global_account_short_pct: float | None = None
    global_account_ratio: float | None = None
    net_long_change: float | None = None
    net_short_change: float | None = None
    net_long_change_cum: float | None = None
    net_short_change_cum: float | None = None
    net_position_change_cum: float | None = None
    liq_notional_below_mark_usd: float | None = None
    liq_notional_above_mark_usd: float | None = None
    liq_nearest_long_price: float | None = None
    liq_nearest_short_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def has_any_ratio(self) -> bool:
        return any(
            v is not None
            for v in (
                self.top_account_ratio,
                self.top_position_ratio,
                self.global_account_ratio,
                self.net_position_change_cum,
            )
        )


def build_market_context(
    *,
    symbol: str,
    mark_price: float | None,
    top_account_row: dict[str, Any] | None,
    top_position_row: dict[str, Any] | None,
    global_account_row: dict[str, Any] | None,
    net_position_row: dict[str, Any] | None,
    liq_summary: dict[str, float | None] | None,
) -> CoinGlassMarketContext:
    coin = symbol_to_coinglass_coin(symbol)
    pair = symbol_to_coinglass_pair(symbol)
    fields: dict[str, Any] = {
        "symbol": symbol,
        "coin": coin,
        "pair": pair,
        "mark_price": mark_price,
    }
    if top_account_row:
        fields.update(parse_top_account_ratio(top_account_row))
    if top_position_row:
        fields.update(parse_top_position_ratio(top_position_row))
    if global_account_row:
        fields.update(parse_global_account_ratio(global_account_row))
    if net_position_row:
        fields.update(parse_net_position(net_position_row))
    if liq_summary:
        fields.update(liq_summary)
    return CoinGlassMarketContext(**fields)


def _pct(v: float | None) -> str:
    return f"{v:.2f}%" if v is not None else "—"


def _num(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1e6:
        return f"{v/1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"{v/1e3:.1f}k"
    return f"{v:.4g}"


def format_market_context(ctx: CoinGlassMarketContext) -> str:
    """多行中文摘要（日志 / Telegram / LLM）。"""
    lines = [
        f"CoinGlass · {ctx.coin} ({ctx.pair})"
        + (f" · 现价 {_num(ctx.mark_price)}" if ctx.mark_price else ""),
        f"大户账号多空比  多 {_pct(ctx.top_account_long_pct)} / 空 {_pct(ctx.top_account_short_pct)} · 比值 {_num(ctx.top_account_ratio)}",
        f"大户持仓多空比  多 {_pct(ctx.top_position_long_pct)} / 空 {_pct(ctx.top_position_short_pct)} · 比值 {_num(ctx.top_position_ratio)}",
        f"全市场人数多空  多 {_pct(ctx.global_account_long_pct)} / 空 {_pct(ctx.global_account_short_pct)} · 比值 {_num(ctx.global_account_ratio)}",
        (
            "净多空(累计变化)  "
            f"净多 {_num(ctx.net_long_change_cum)} · 净空 {_num(ctx.net_short_change_cum)} · "
            f"净仓 {_num(ctx.net_position_change_cum)}"
        ),
    ]
    if any(
        v is not None
        for v in (
            ctx.liq_notional_below_mark_usd,
            ctx.liq_notional_above_mark_usd,
            ctx.liq_nearest_long_price,
            ctx.liq_nearest_short_price,
        )
    ):
        lines.append(
            "清算地图(1d聚合)  "
            f"下方多头清算簇 ${_num(ctx.liq_notional_below_mark_usd)} @ {_num(ctx.liq_nearest_long_price)} · "
            f"上方空头清算簇 ${_num(ctx.liq_notional_above_mark_usd)} @ {_num(ctx.liq_nearest_short_price)}"
        )
    return "\n".join(lines)


def format_market_context_for_llm(ctx: CoinGlassMarketContext) -> str:
    return format_market_context(ctx)


# 选币排名维度名（与 symbol_universe._RANK_METRICS 一致）
CG_DERIV_RANK_METRICS = frozenset(
    {
        "cg_top_account_long",
        "cg_top_position_long",
        "cg_global_long",
        "cg_net_position",
        "cg_liq_below",
        "cg_liq_above",
    }
)


def rank_metrics_from_context(ctx: CoinGlassMarketContext) -> dict[str, float]:
    """从快照提取可用于 SYMBOL_CANDIDATES_RANK_BY 的标量。"""
    out: dict[str, float] = {}
    if ctx.top_account_long_pct is not None:
        out["cg_top_account_long"] = float(ctx.top_account_long_pct)
    if ctx.top_position_long_pct is not None:
        out["cg_top_position_long"] = float(ctx.top_position_long_pct)
    if ctx.global_account_long_pct is not None:
        out["cg_global_long"] = float(ctx.global_account_long_pct)
    if ctx.net_position_change_cum is not None:
        out["cg_net_position"] = float(ctx.net_position_change_cum)
    if ctx.liq_notional_below_mark_usd is not None:
        out["cg_liq_below"] = float(ctx.liq_notional_below_mark_usd)
    if ctx.liq_notional_above_mark_usd is not None:
        out["cg_liq_above"] = float(ctx.liq_notional_above_mark_usd)
    return out


def derivatives_exit_reason(
    side: str,
    *,
    mark: float,
    settings: Settings,
    ctx: CoinGlassMarketContext | None,
) -> str | None:
    """CoinGlass 微观结构离场；未触发返回 None。side 为 long/short。"""
    if ctx is None or side not in ("long", "short"):
        return None

    crowd_acc = float(settings.exit_cg_top_account_crowd_pct)
    if crowd_acc > 0.0:
        if side == "long" and ctx.top_account_long_pct is not None and ctx.top_account_long_pct >= crowd_acc:
            return f"cg_crowd_top_account long={ctx.top_account_long_pct:.1f}% >= {crowd_acc:.1f}%"
        if side == "short" and ctx.top_account_short_pct is not None and ctx.top_account_short_pct >= crowd_acc:
            return f"cg_crowd_top_account short={ctx.top_account_short_pct:.1f}% >= {crowd_acc:.1f}%"

    crowd_pos = float(settings.exit_cg_top_position_crowd_pct)
    if crowd_pos > 0.0:
        if side == "long" and ctx.top_position_long_pct is not None and ctx.top_position_long_pct >= crowd_pos:
            return f"cg_crowd_top_position long={ctx.top_position_long_pct:.1f}% >= {crowd_pos:.1f}%"
        if side == "short" and ctx.top_position_short_pct is not None and ctx.top_position_short_pct >= crowd_pos:
            return f"cg_crowd_top_position short={ctx.top_position_short_pct:.1f}% >= {crowd_pos:.1f}%"

    crowd_global = float(settings.exit_cg_global_long_crowd_pct)
    if crowd_global > 0.0:
        if side == "long" and ctx.global_account_long_pct is not None and ctx.global_account_long_pct >= crowd_global:
            return f"cg_crowd_global long={ctx.global_account_long_pct:.1f}% >= {crowd_global:.1f}%"
        if side == "short" and ctx.global_account_short_pct is not None and ctx.global_account_short_pct >= crowd_global:
            return f"cg_crowd_global short={ctx.global_account_short_pct:.1f}% >= {crowd_global:.1f}%"

    net_against = float(settings.exit_cg_net_position_against)
    if net_against > 0.0 and ctx.net_position_change_cum is not None:
        npc = ctx.net_position_change_cum
        if side == "long" and npc <= -net_against:
            return f"cg_net_against long net_position_cum={npc:.4g} <= -{net_against:.4g}"
        if side == "short" and npc >= net_against:
            return f"cg_net_against short net_position_cum={npc:.4g} >= {net_against:.4g}"

    liq_usd = float(settings.exit_cg_liq_cluster_usd)
    liq_dist = float(settings.exit_cg_liq_cluster_dist_pct)
    if liq_usd > 0.0 and liq_dist > 0.0 and mark > 0.0:
        if side == "long":
            below = ctx.liq_notional_below_mark_usd
            near = ctx.liq_nearest_long_price
            if below is not None and below >= liq_usd and near is not None and near > 0:
                dist_pct = (mark - near) / mark * 100.0
                if dist_pct <= liq_dist:
                    return (
                        f"cg_liq_cluster long below=${below:.0f} @ {near:.4g} "
                        f"dist={dist_pct:.2f}% <= {liq_dist:.2f}%"
                    )
        if side == "short":
            above = ctx.liq_notional_above_mark_usd
            near = ctx.liq_nearest_short_price
            if above is not None and above >= liq_usd and near is not None and near > 0:
                dist_pct = (near - mark) / mark * 100.0
                if dist_pct <= liq_dist:
                    return (
                        f"cg_liq_cluster short above=${above:.0f} @ {near:.4g} "
                        f"dist={dist_pct:.2f}% <= {liq_dist:.2f}%"
                    )
    return None
