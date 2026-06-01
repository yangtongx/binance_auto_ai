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
    {"abs_change", "change", "open_interest", "quote_volume", "liquidity", "random"}
)
_METRIC_ALIASES = {"volume": "quote_volume", "liquidity": "quote_volume"}
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
    if mode == "available_margin_leverage" and available_margin_usdt is not None and available_margin_usdt > 0:
        return min(cap, float(available_margin_usdt) * settings.leverage * pct)
    if mode == "equity_leverage" and equity_usdt is not None and equity_usdt > 0:
        return min(cap, float(equity_usdt) * settings.leverage * pct)
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
    if metric in ("abs_change", "change"):
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


def select_top_usdm_candidates(
    ex: ccxt.binanceusdm,
    settings: Settings,
    *,
    equity_usdt: float | None = None,
    available_margin_usdt: float | None = None,
) -> list[str]:
    """
    Filter USDT linear perpetuals, rank by ``SYMBOL_CANDIDATES_RANK_BY``, return top N.

    ``SYMBOL_CANDIDATES_MIN_QUOTE_VOLUME_USDT`` is only a liquidity floor (0 = off), not the rank key.
    """
    exclude = {s.strip() for s in parse_symbol_candidates(settings.symbol_candidates_exclude) if s.strip()}
    metrics = settings.candidate_rank_metrics()
    weights = settings.candidate_rank_weights()

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
    eligible: list[tuple[str, dict[str, float]]] = []
    skipped_pump: list[tuple[str, float]] = []

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
        for metric in metrics:
            score = _rank_score(metric, symbol=sym, ticker=ticker, last=last_f, refresh_seed=refresh_seed)
            if score is not None:
                metric_values[metric] = score
        if metric_values:
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
        vals = [mv[metric] for _sym, mv in eligible]
        norms = _minmax_normalize(vals)
        norm_by_metric[metric] = {sym: norms[i] for i, (sym, _mv) in enumerate(eligible)}

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

    rows.sort(key=lambda x: (-x[0], x[1]))
    count = int(settings.symbol_candidates_count)
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

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._symbols: list[str] = []
        self._last_refresh_monotonic = 0.0

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
