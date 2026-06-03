"""自动候选池：按流动性/OI/涨跌幅等复合排名，从币安全市场筛 USDT 永续。"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import ccxt

from binance_auto_ai.config import Settings
from binance_auto_ai.order_utils import min_order_notional_usdt
from binance_auto_ai.positions import fetch_futures_usdt_balance
from binance_auto_ai.symbol_picker import parse_symbol_candidates

logger = logging.getLogger(__name__)

_AUTO_CANDIDATE_TOKENS = frozenset({"auto", "top", "*"})
_STABLE_BASES = frozenset({"USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDP", "USDT"})
_RANK_METRICS = frozenset(
    {
        "abs_change",
        "change",
        "open_interest",
        "quote_volume",
        "liquidity",
        "random",
        # 趋势/动量（与交易策略对齐，需逐币拉 OHLCV，见 _MOMENTUM_*）
        "momentum",
        # 资金费率（永续拥挤度，需 fetch_funding_rates）
        "funding",
        "abs_funding",
        # CoinGlass 聚合持仓量变化%（跨交易所，需 COINGLASS_API_KEY）
        "cg_oi_change",
        # CoinGlass 微观结构（逐币 API，仅对流动性短名单拉取）
        "cg_top_account_long",
        "cg_top_position_long",
        "cg_global_long",
        "cg_net_position",
        "cg_liq_below",
        "cg_liq_above",
    }
)
_METRIC_ALIASES = {
    "volume": "quote_volume",
    "liquidity": "quote_volume",
    "trend": "momentum",
    "funding_rate": "funding",
    "abs_funding_rate": "abs_funding",
    "oi_change": "cg_oi_change",
    "cg_oi": "cg_oi_change",
    "top_account_long": "cg_top_account_long",
    "top_position_long": "cg_top_position_long",
    "global_long": "cg_global_long",
    "net_position": "cg_net_position",
    "liq_below": "cg_liq_below",
    "liq_above": "cg_liq_above",
}
# 需要逐币 OHLCV 才能算的指标（两段式：先按流动性短名单，再对短名单拉 K 线）
_OHLCV_RANK_METRICS = frozenset({"momentum"})
# 需要 fetch_funding_rates 的指标
_FUNDING_RANK_METRICS = frozenset({"funding", "abs_funding"})
# 需要 CoinGlass coins-markets 批量快照
_COINGLASS_BULK_RANK_METRICS = frozenset({"cg_oi_change"})
# 需要逐币 CoinGlass 多空比/清算地图（流动性短名单）
_COINGLASS_DERIV_RANK_METRICS = frozenset(
    {
        "cg_top_account_long",
        "cg_top_position_long",
        "cg_global_long",
        "cg_net_position",
        "cg_liq_below",
        "cg_liq_above",
    }
)
_COINGLASS_RANK_METRICS = _COINGLASS_BULK_RANK_METRICS | _COINGLASS_DERIV_RANK_METRICS
# momentum 短名单大小（避免对全市场逐币拉 OHLCV）：max(count * 倍数, 下限)
_MOMENTUM_SHORTLIST_MULT = 5
_MOMENTUM_SHORTLIST_MIN = 30
# 自动扫描结果少于 2 个交易对时的回退列表（API/行情缺口、过滤过严）
_FALLBACK_CANDIDATES = (
    "DOGE/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "LINK/USDT:USDT",
    "ADA/USDT:USDT",
)


def parse_rank_metrics(raw: str) -> list[str]:
    out: list[str] = []
    for part in str(raw).split(","):
        p = part.strip().lower()
        p = _METRIC_ALIASES.get(p, p)
        if not p or p not in _RANK_METRICS:
            continue
        if p not in out:
            out.append(p)
    return out


def parse_rank_weights(metrics: list[str], raw: str) -> list[float]:
    if not metrics:
        return []
    text = (raw or "").strip()
    if not text:
        return [1.0 / len(metrics)] * len(metrics)
    parts = [float(x.strip()) for x in text.split(",") if x.strip()]
    if len(parts) != len(metrics):
        logger.warning(
            "rank weights count %s != metrics count %s; using equal weights",
            len(parts),
            len(metrics),
        )
        return [1.0 / len(metrics)] * len(metrics)
    total = sum(parts)
    if total <= 0:
        raise ValueError("rank weights must sum to a positive value")
    return [p / total for p in parts]


def is_auto_symbol_candidates(raw: str) -> bool:
    return raw.strip().lower() in _AUTO_CANDIDATE_TOKENS


def affordable_max_notional_usdt(
    settings: Settings,
    *,
    equity_usdt: float | None,
    available_margin_usdt: float | None,
) -> float:
    """Upper bound used to skip symbols whose exchange min notional is unaffordable."""
    cap = float(settings.max_notional_usdt)
    pct = settings.strategy_size_pct / 100.0
    mode = settings.position_sizing
    # LEVERAGE_MODE=max 时各币最大杠杆不一（且查询昂贵），用较大假设值估可负担额度，避免误剔除
    lev = 125.0 if settings.leverage_mode == "max" else settings.leverage
    if mode == "available_margin_leverage" and available_margin_usdt is not None and available_margin_usdt > 0:
        return min(cap, float(available_margin_usdt) * lev * pct)
    if mode == "equity_leverage" and equity_usdt is not None and equity_usdt > 0:
        return min(cap, float(equity_usdt) * lev * pct)
    return cap


def _is_usdt_linear_perp(market: dict[str, Any]) -> bool:
    sym = str(market.get("symbol") or "")
    if not sym.endswith(":USDT"):
        return False
    if market.get("quote") != "USDT":
        return False
    if not market.get("active", True):
        return False
    return bool(market.get("swap")) or market.get("type") == "swap"


def _base_asset(symbol: str) -> str:
    return symbol.split("/")[0].upper()


def _ticker_quote_volume_usdt(ticker: dict[str, Any]) -> float:
    qv = ticker.get("quoteVolume")
    if qv is not None:
        try:
            v = float(qv)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    last = ticker.get("last") or ticker.get("close")
    base_vol = ticker.get("baseVolume")
    try:
        if last is not None and base_vol is not None:
            return float(last) * float(base_vol)
    except (TypeError, ValueError):
        pass
    return 0.0


def _ticker_percentage(ticker: dict[str, Any]) -> float | None:
    raw = ticker.get("percentage")
    if raw is None:
        info = ticker.get("info")
        if isinstance(info, dict):
            raw = info.get("priceChangePercent")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _ticker_open_interest_usdt(ticker: dict[str, Any], *, last: float) -> float:
    info = ticker.get("info")
    if isinstance(info, dict):
        for key in ("openInterest", "openInterestValue"):
            raw = info.get(key)
            if raw is None:
                continue
            try:
                oi = float(raw)
            except (TypeError, ValueError):
                continue
            if key == "openInterestValue" or oi > last * 1000:
                return oi if oi > 0 else 0.0
            if last > 0:
                return oi * last
    return 0.0


def _rank_score(
    rank_by: str,
    *,
    symbol: str,
    ticker: dict[str, Any],
    last: float,
    refresh_seed: str,
) -> float | None:
    if rank_by == "quote_volume":
        v = _ticker_quote_volume_usdt(ticker)
        return v if v > 0 else None
    if rank_by == "abs_change":
        pct = _ticker_percentage(ticker)
        return abs(pct) if pct is not None else None
    if rank_by == "change":
        pct = _ticker_percentage(ticker)
        return pct if pct is not None else None
    if rank_by == "open_interest":
        oi = _ticker_open_interest_usdt(ticker, last=last)
        return oi if oi > 0 else None
    if rank_by == "random":
        digest = hashlib.sha256(f"{refresh_seed}|{symbol}".encode()).hexdigest()
        return float(int(digest[:12], 16))
    return None


def _format_score(metric: str, score: float) -> str:
    if metric in ("quote_volume", "liquidity"):
        return f"vol={score / 1e6:.1f}M"
    if metric in ("abs_change", "change", "cg_oi_change"):
        return f"{score:+.2f}%"
    if metric == "open_interest":
        return f"{score / 1e6:.2f}M"
    return f"{score:.0f}"


def _minmax_normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _rank_normalize(values: list[float]) -> list[float]:
    """分数排名百分位归一到 [0,1]（抗极值：单个超大值不会把其余压到≈0）。

    并列取平均名次；全相等返回 0.5。比 min-max 更稳健，因为只看相对次序、不看绝对差距。
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    avg_rank = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # i..j 为并列区间，取平均名次
        mean_pos = (i + j) / 2.0
        for k in range(i, j + 1):
            avg_rank[order[k]] = mean_pos
        i = j + 1
    denom = float(n - 1)
    return [r / denom for r in avg_rank]


def _resolve_active_metrics(
    requested: list[str],
    weights: list[float],
    eligible: list[tuple[str, dict[str, float]]],
    *,
    min_coverage: float = 0.05,
) -> tuple[list[str], list[float]]:
    """Keep rank metrics that at least ``min_coverage`` fraction of eligible symbols support."""
    if not eligible:
        return [], []
    n = len(eligible)
    active: list[str] = []
    active_weights: list[float] = []
    for metric, weight in zip(requested, weights, strict=True):
        have = sum(1 for _sym, mv in eligible if metric in mv)
        if have >= max(1, int(n * min_coverage)):
            active.append(metric)
            active_weights.append(weight)
    if not active:
        return [], []
    total = sum(active_weights)
    return active, [w / total for w in active_weights]


def _composite_rank_score(
    metric_values: dict[str, float],
    *,
    metrics: list[str],
    weights: list[float],
    norm_by_metric: dict[str, dict[str, float]],
    symbol: str,
) -> float:
    total = 0.0
    for metric, weight in zip(metrics, weights, strict=True):
        if metric not in metric_values:
            continue
        total += weight * norm_by_metric[metric][symbol]
    tie = abs(metric_values.get("abs_change", metric_values.get("change", 0.0)))
    return total + tie * 1e-9


def _fallback_candidates(
    ex: ccxt.binanceusdm,
    *,
    exclude: set[str],
    count: int,
) -> list[str]:
    out: list[str] = []
    for sym in _FALLBACK_CANDIDATES:
        if sym in exclude:
            continue
        if sym not in ex.markets or not _is_usdt_linear_perp(ex.markets[sym]):
            continue
        out.append(sym)
        if len(out) >= count:
            break
    return out


def _momentum_strength(ohlcv: list[list[float]], *, fast: int, slow: int) -> float | None:
    """趋势强度 = |SMA_fast - SMA_slow| / last，与 SMA 交叉策略同向（取绝对值=方向无关的强度）。"""
    if slow < 2 or fast < 1 or fast >= slow:
        return None
    closes: list[float] = []
    for row in ohlcv:
        if not row or len(row) < 5:
            continue
        try:
            closes.append(float(row[4]))
        except (TypeError, ValueError):
            continue
    if len(closes) < slow + 1:
        return None
    last = closes[-1]
    if last <= 0:
        return None
    sma_fast = sum(closes[-fast:]) / float(fast)
    sma_slow = sum(closes[-slow:]) / float(slow)
    strength = abs(sma_fast - sma_slow) / last
    return strength if strength >= 0 else None


def _attach_momentum_scores(
    ex: ccxt.binanceusdm,
    settings: Settings,
    passed: list[tuple[str, dict[str, Any], float, dict[str, float]]],
    *,
    count: int,
) -> set[str]:
    """对流动性短名单逐币拉 OHLCV 计算 momentum，写回 metric_values；返回入选短名单的符号集合。

    两段式：先按 24h 成交额排序取 top-N（N=max(count*5,30)），只对短名单拉 K 线，
    避免对全市场（数百个永续）逐币请求。返回的集合用于把最终排序范围收敛到短名单。
    """
    fast = int(settings.strategy_fast)
    slow = int(settings.strategy_slow)
    if fast >= slow:
        fast = max(1, slow // 3)
    shortlist_n = min(len(passed), max(count * _MOMENTUM_SHORTLIST_MULT, _MOMENTUM_SHORTLIST_MIN))
    ranked = sorted(
        passed,
        key=lambda row: _ticker_quote_volume_usdt(row[1]),
        reverse=True,
    )
    shortlist = ranked[:shortlist_n]
    limit = max(slow * 2, slow + 5, 60)
    in_shortlist: set[str] = set()
    for sym, _ticker, _last, metric_values in shortlist:
        in_shortlist.add(sym)
        try:
            ohlcv = ex.fetch_ohlcv(sym, timeframe=settings.timeframe, limit=limit)
        except Exception as e:  # noqa: BLE001 - 单个币拉取失败不应中断整池
            logger.debug("momentum ohlcv fetch failed for %s: %s", sym, e)
            continue
        score = _momentum_strength(ohlcv, fast=fast, slow=slow)
        if score is not None:
            metric_values["momentum"] = score
    return in_shortlist


def _liquidity_shortlist_symbols(
    passed: list[tuple[str, dict[str, Any], float, dict[str, float]]],
    *,
    count: int,
) -> set[str]:
    shortlist_n = min(len(passed), max(count * _MOMENTUM_SHORTLIST_MULT, _MOMENTUM_SHORTLIST_MIN))
    ranked = sorted(
        passed,
        key=lambda row: _ticker_quote_volume_usdt(row[1]),
        reverse=True,
    )
    return {sym for sym, _t, _l, _mv in ranked[:shortlist_n]}


def _attach_coinglass_derivative_scores(
    coinglass: Any,
    settings: Settings,
    passed: list[tuple[str, dict[str, Any], float, dict[str, float]]],
    *,
    only_symbols: set[str],
    metrics: list[str],
) -> None:
    """对短名单逐币拉 CoinGlass 多空比/净仓/清算地图，写回 metric_values。"""
    from binance_auto_ai.coinglass_derivatives import rank_metrics_from_context

    want = [m for m in metrics if m in _COINGLASS_DERIV_RANK_METRICS]
    if not want or coinglass is None:
        return
    for sym, _ticker, last_f, metric_values in passed:
        if sym not in only_symbols:
            continue
        try:
            ctx = coinglass.market_context(sym, mark_price=last_f)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            logger.debug("cg derivative metrics failed for %s: %s", sym, e)
            continue
        if ctx is None:
            continue
        for k, v in rank_metrics_from_context(ctx).items():
            if k in want:
                metric_values[k] = v


def _attach_funding_scores(
    ex: ccxt.binanceusdm,
    passed: list[tuple[str, dict[str, Any], float, dict[str, float]]],
    *,
    want_funding: bool,
    want_abs_funding: bool,
) -> None:
    """通过 fetch_funding_rates 一次性拉资金费率，写回 funding/abs_funding；失败则跳过（指标自动降级）。"""
    if not (want_funding or want_abs_funding):
        return
    try:
        rates = ex.fetch_funding_rates()
    except Exception as e:  # noqa: BLE001 - 资金费率不可用时优雅降级
        logger.warning("fetch_funding_rates failed (%s); funding metric skipped", e)
        return
    if not isinstance(rates, dict):
        return
    for sym, _ticker, _last, metric_values in passed:
        row = rates.get(sym)
        if not isinstance(row, dict):
            continue
        raw = row.get("fundingRate")
        if raw is None:
            info = row.get("info")
            if isinstance(info, dict):
                raw = info.get("fundingRate") or info.get("lastFundingRate")
        try:
            rate = float(raw)
        except (TypeError, ValueError):
            continue
        if want_funding:
            metric_values["funding"] = rate
        if want_abs_funding:
            metric_values["abs_funding"] = abs(rate)


def select_top_usdm_candidates(
    ex: ccxt.binanceusdm,
    settings: Settings,
    *,
    equity_usdt: float | None = None,
    available_margin_usdt: float | None = None,
    coinglass: Any = None,
) -> list[str]:
    """
    Filter USDT linear perpetuals, rank by ``SYMBOL_CANDIDATES_RANK_BY``, return top N.

    ``SYMBOL_CANDIDATES_MIN_QUOTE_VOLUME_USDT`` is only a liquidity floor (0 = off), not the rank key.
    ``coinglass`` 为可选的 ``CoinglassClient``（None 时按需自建；key 为空则相关维度/过滤自动关闭）。
    """
    exclude = {s.strip() for s in parse_symbol_candidates(settings.symbol_candidates_exclude) if s.strip()}
    metrics = settings.candidate_rank_metrics()
    weights = settings.candidate_rank_weights()

    # CoinGlass 数据（聚合 OI / 资金费率过滤 / 微观结构排名）；失败/未启用 → 空 map，相关功能自动降级
    need_coinglass_bulk = settings.coinglass_enabled() and (
        bool(_COINGLASS_BULK_RANK_METRICS.intersection(metrics))
        or settings.coinglass_max_abs_funding_pct > 0.0
    )
    need_coinglass_deriv = settings.coinglass_derivatives_enabled() and bool(
        _COINGLASS_DERIV_RANK_METRICS.intersection(metrics)
    )
    need_coinglass = need_coinglass_bulk or need_coinglass_deriv
    cg_map: dict[str, dict[str, float | None]] = {}
    if need_coinglass:
        if coinglass is None:
            from binance_auto_ai.coinglass import build_coinglass_client

            coinglass = build_coinglass_client(settings)
        if coinglass is not None:
            try:
                cg_map = coinglass.coin_metrics()
            except Exception as e:  # noqa: BLE001
                logger.warning("CoinGlass coin_metrics failed (%s); cg metrics/filter skipped", e)
                cg_map = {}
    max_abs_funding = float(settings.coinglass_max_abs_funding_pct)
    skipped_funding: list[tuple[str, float]] = []

    try:
        tickers = ex.fetch_tickers()
    except ccxt.BaseError as e:
        logger.warning("fetch_tickers failed for auto candidates (%s)", e)
        tickers = {}
    if not tickers:
        logger.warning(
            "fetch_tickers returned empty — volume floor skipped; check network/API access to fapi.binance.com"
        )

    affordable = affordable_max_notional_usdt(
        settings, equity_usdt=equity_usdt, available_margin_usdt=available_margin_usdt
    )
    min_vol = float(settings.symbol_candidates_min_quote_volume_usdt)
    max_abs_change = float(settings.symbol_candidates_max_abs_change_pct)
    refresh_seed = time.strftime("%Y-%m-%d-%H", time.gmtime())
    skipped_pump: list[tuple[str, float]] = []
    # 仅用 ticker 即可算的指标在主循环里算；momentum/funding/coinglass 需额外数据，单独补
    ticker_metrics = [
        m
        for m in metrics
        if m not in _OHLCV_RANK_METRICS and m not in _FUNDING_RANK_METRICS and m not in _COINGLASS_RANK_METRICS
    ]
    # (sym, ticker, last, metric_values)
    passed: list[tuple[str, dict[str, Any], float, dict[str, float]]] = []

    for sym, market in ex.markets.items():
        if sym in exclude:
            continue
        if not _is_usdt_linear_perp(market):
            continue
        base = _base_asset(sym)
        if base in _STABLE_BASES:
            continue
        ticker = tickers.get(sym) or {}
        if min_vol > 0:
            qv = _ticker_quote_volume_usdt(ticker)
            if qv > 0 and qv < min_vol:
                continue
        if max_abs_change > 0:
            pct = _ticker_percentage(ticker)
            if pct is not None and abs(pct) > max_abs_change:
                skipped_pump.append((sym, pct))
                continue
        if max_abs_funding > 0 and cg_map:
            cg_row = cg_map.get(_base_asset(sym))
            if cg_row is not None:
                fr = cg_row.get("funding_rate")
                if fr is not None and abs(fr) > max_abs_funding:
                    skipped_funding.append((sym, fr))
                    continue
        last = ticker.get("last") or ticker.get("close")
        try:
            last_f = float(last) if last is not None else 0.0
        except (TypeError, ValueError):
            last_f = 0.0
        if last_f <= 0:
            continue
        if settings.symbol_candidates_filter_min_notional:
            try:
                min_n = min_order_notional_usdt(ex, sym, last=last_f)
            except Exception:
                min_n = 0.0
            if min_n > affordable * 0.98:
                logger.debug(
                    "auto candidates skip %s: min_notional≈%.2f > affordable≈%.2f",
                    sym,
                    min_n,
                    affordable,
                )
                continue
        metric_values: dict[str, float] = {}
        for metric in ticker_metrics:
            score = _rank_score(metric, symbol=sym, ticker=ticker, last=last_f, refresh_seed=refresh_seed)
            if score is not None:
                metric_values[metric] = score
        if "cg_oi_change" in metrics and cg_map:
            cg_row = cg_map.get(_base_asset(sym))
            if cg_row is not None and cg_row.get("oi_change_pct") is not None:
                metric_values["cg_oi_change"] = float(cg_row["oi_change_pct"])
        passed.append((sym, ticker, last_f, metric_values))

    # 资金费率维度（一次性拉取，写回各币 metric_values）
    _attach_funding_scores(
        ex,
        passed,
        want_funding="funding" in metrics,
        want_abs_funding="abs_funding" in metrics,
    )

    count = int(settings.symbol_candidates_count)
    restrict_shortlist: set[str] | None = None

    # 趋势/动量维度：两段式（流动性短名单 → 逐币 OHLCV）
    if any(m in _OHLCV_RANK_METRICS for m in metrics) and passed:
        restrict_shortlist = _attach_momentum_scores(ex, settings, passed, count=count)

    # CoinGlass 微观结构：与动量共用流动性短名单（无动量时单独建短名单）
    if need_coinglass_deriv and passed and coinglass is not None:
        deriv_syms = restrict_shortlist or _liquidity_shortlist_symbols(passed, count=count)
        _attach_coinglass_derivative_scores(
            coinglass,
            settings,
            passed,
            only_symbols=deriv_syms,
            metrics=metrics,
        )
        if restrict_shortlist is None and _COINGLASS_DERIV_RANK_METRICS.intersection(metrics):
            restrict_shortlist = deriv_syms

    eligible: list[tuple[str, dict[str, float]]] = []
    for sym, _ticker, _last, metric_values in passed:
        if not metric_values:
            continue
        if restrict_shortlist is not None and sym not in restrict_shortlist:
            continue
        eligible.append((sym, metric_values))

    active_metrics, active_weights = _resolve_active_metrics(metrics, weights, eligible)
    if not active_metrics:
        logger.warning(
            "auto candidates: no rank metrics had data (requested %s); using fallback list",
            ",".join(metrics),
        )
    else:
        if set(active_metrics) != set(metrics):
            logger.info(
                "auto candidates: using metrics with data only: %s (requested %s)",
                ",".join(active_metrics),
                ",".join(metrics),
            )

    norm_by_metric: dict[str, dict[str, float]] = {}
    for metric in active_metrics:
        # 只对拥有该指标的币归一，避免缺值币被当成 0 拉低/顶高分布
        present = [(sym, mv[metric]) for sym, mv in eligible if metric in mv]
        norms = _rank_normalize([v for _sym, v in present])
        norm_by_metric[metric] = {sym: norms[i] for i, (sym, _v) in enumerate(present)}

    rows: list[tuple[float, str]] = []
    for sym, metric_values in eligible:
        composite = _composite_rank_score(
            metric_values,
            metrics=active_metrics,
            weights=active_weights,
            norm_by_metric=norm_by_metric,
            symbol=sym,
        )
        rows.append((composite, sym))

    if skipped_pump:
        sample = ", ".join(f"{s}({p:+.1f}%)" for s, p in skipped_pump[:5])
        more = "" if len(skipped_pump) <= 5 else f" …(+{len(skipped_pump) - 5})"
        logger.info(
            "auto candidates: skipped %s pump/dump symbols (|24h%%| > %.1f): %s%s",
            len(skipped_pump),
            max_abs_change,
            sample,
            more,
        )

    if skipped_funding:
        sample = ", ".join(f"{s}({fr:+.4f})" for s, fr in skipped_funding[:5])
        more = "" if len(skipped_funding) <= 5 else f" …(+{len(skipped_funding) - 5})"
        logger.info(
            "auto candidates: skipped %s crowded symbols (|CoinGlass funding| > %s): %s%s",
            len(skipped_funding),
            max_abs_funding,
            sample,
            more,
        )

    rows.sort(key=lambda x: (-x[0], x[1]))
    picked = [sym for _score, sym in rows[:count]]
    if len(picked) < 2:
        logger.warning(
            "auto candidates found only %s symbols after filters (eligible=%s, affordable≈%.2f USDT); "
            "using fallback",
            len(picked),
            len(eligible),
            affordable,
        )
        picked = _fallback_candidates(ex, exclude=exclude, count=count)
    if picked:
        raw_map = {sym: mv for sym, mv in eligible}
        bits: list[str] = []
        for sym in picked:
            mv = raw_map.get(sym, {})
            if mv:
                detail = "+".join(
                    f"{m}:{_format_score(m, mv[m])}" for m in active_metrics if m in mv
                )
                bits.append(f"{sym}({detail})")
            else:
                bits.append(f"{sym}(fallback)")
        weight_s = ",".join(f"{m}={w:.2f}" for m, w in zip(active_metrics, active_weights, strict=True))
        logger.info(
            "auto SYMBOL_CANDIDATES top %s composite [%s] weights [%s] (min_quote_vol=%.0f): %s",
            len(picked),
            ",".join(active_metrics) if active_metrics else "fallback",
            weight_s if active_metrics else "n/a",
            min_vol,
            ", ".join(bits),
        )
    return picked


class CandidatePool:
    """signal_pick 候选池：手动列表或按 SYMBOL_CANDIDATES_REFRESH_* 定时自动刷新。"""

    def __init__(self, settings: Settings, *, coinglass: Any = None) -> None:
        self._settings = settings
        self._symbols: list[str] = []
        self._last_refresh_monotonic = 0.0
        self._coinglass = coinglass
        if self._coinglass is None and settings.coinglass_enabled():
            from binance_auto_ai.coinglass import build_coinglass_client

            self._coinglass = build_coinglass_client(settings)

    @property
    def coinglass(self) -> Any:
        return self._coinglass

    @property
    def is_auto(self) -> bool:
        return self._settings.symbol_candidates_is_auto()

    def should_refresh(self) -> bool:
        if not self._symbols:
            return True
        if not self.is_auto:
            return False
        age_s = time.monotonic() - self._last_refresh_monotonic
        return age_s >= self._refresh_interval_sec()

    def _refresh_interval_sec(self) -> float:
        minutes = float(self._settings.symbol_candidates_refresh_minutes)
        if minutes > 0.0:
            return minutes * 60.0
        return float(self._settings.symbol_candidates_refresh_hours) * 3600.0

    def refresh(self, ex: ccxt.binanceusdm) -> list[str]:
        if self.is_auto:
            equity, margin = fetch_futures_usdt_balance(ex)
            picked = select_top_usdm_candidates(
                ex,
                self._settings,
                equity_usdt=equity,
                available_margin_usdt=margin,
                coinglass=self._coinglass,
            )
            if len(picked) < 2:
                picked = _fallback_candidates(
                    ex,
                    exclude={
                        s.strip()
                        for s in parse_symbol_candidates(self._settings.symbol_candidates_exclude)
                        if s.strip()
                    },
                    count=int(self._settings.symbol_candidates_count),
                )
            if len(picked) < 2:
                raise RuntimeError(
                    "auto SYMBOL_CANDIDATES could not resolve ≥2 symbols; "
                    "set SYMBOL_CANDIDATES to a manual list or fix Binance API connectivity"
                )
            self._symbols = picked
        else:
            self._symbols = self._settings.manual_candidate_symbols()
            if len(self._symbols) < 2:
                raise RuntimeError("manual SYMBOL_CANDIDATES needs at least 2 symbols")
        self._last_refresh_monotonic = time.monotonic()
        mode = "auto" if self.is_auto else "manual"
        logger.info("candidate pool refreshed (%s): %s", mode, ", ".join(self._symbols))
        return self._symbols

    def symbols(self) -> list[str]:
        if len(self._symbols) < 2:
            raise RuntimeError("candidate pool not initialized; call refresh() first")
        return list(self._symbols)
