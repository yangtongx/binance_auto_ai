"""观望时的时机参考：给出做多/做空的具体触发价位（高点、均线、金叉死叉等）。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from binance_auto_ai.backtest.indicators import (
    closes_array,
    ema_series,
    macd_signal_last,
    rsi_wilder_series,
    sma_series,
)
from binance_auto_ai.config import Settings
from binance_auto_ai.schemas import Action, LLMSignal


@dataclass(frozen=True)
class PriceLevel:
    """One actionable price level for the user."""

    label: str
    price: float
    op: str = ">="  # >= 做多触发，<= 做空触发，~ 近似

    def line(self) -> str:
        op_map = {">=": "≥", "<=": "≤", "~": "≈", ">": ">", "<": "<"}
        sym = op_map.get(self.op, self.op)
        return f"{self.label} {sym} {_fmt_price(self.price)}"


@dataclass(frozen=True)
class TimingHint:
    side: str
    title: str
    summary: str
    trigger: str
    levels: tuple[PriceLevel, ...] = ()
    current_price: float = 0.0

    def to_dict(self) -> dict[str, str | float | list[dict[str, str | float]]]:
        return {
            "side": self.side,
            "title": self.title,
            "summary": self.summary,
            "trigger": self.trigger,
            "current_price": self.current_price,
            "current_price_fmt": _fmt_price(self.current_price) if self.current_price > 0 else "",
            "levels": [
                {
                    "label": lv.label,
                    "op": lv.op,
                    "price": lv.price,
                    "price_fmt": _fmt_price(lv.price),
                    "line": lv.line(),
                }
                for lv in self.levels
            ],
        }


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6f}"


def _pct(a: float, b: float) -> float:
    if abs(b) < 1e-18:
        return 0.0
    return (a - b) / b * 100.0


def _last_rsi(closes: np.ndarray, period: int = 14) -> float | None:
    rsi = rsi_wilder_series(closes, period)
    if rsi.size == 0 or np.isnan(rsi[-1]):
        return None
    return float(rsi[-1])


def _swing_levels(ohlcv: list[list[float]], lookback: int = 20) -> tuple[float, float]:
    window = ohlcv[-lookback:] if len(ohlcv) >= lookback else ohlcv
    highs = [float(b[2]) for b in window]
    lows = [float(b[3]) for b in window]
    return max(highs), min(lows)


def _make_hint(
    *,
    side: str,
    title: str,
    levels: list[PriceLevel],
    summary: str,
    current_price: float,
) -> TimingHint:
    if levels:
        trigger = "触发价位：" + " · ".join(lv.line() for lv in levels)
    else:
        trigger = summary
    return TimingHint(
        side=side,
        title=title,
        summary=summary,
        trigger=trigger,
        levels=tuple(levels),
        current_price=current_price,
    )


def _crossover_watch_level(fast: float, slow: float, price: float, *, bullish: bool) -> PriceLevel:
    """Approximate price needed on next close for fast/slow SMA to touch (heuristic)."""
    mid = (fast + slow) / 2.0
    if bullish:
        # 快线低于慢线：价格需向现价与慢线之间的缺口回升
        est = max(mid, slow, price * 1.002)
        return PriceLevel(f"金叉参考价(≈快线上穿慢线)", est, "~")
    est = min(mid, slow, price * 0.998)
    return PriceLevel(f"死叉参考价(≈快线下穿慢线)", est, "~")


def _hints_sma_cross(ohlcv: list[list[float]], settings: Settings) -> list[TimingHint]:
    closes = closes_array(ohlcv)
    fast_n = settings.strategy_fast
    slow_n = settings.strategy_slow
    if closes.size < slow_n + 2:
        return []

    fast = sma_series(closes, fast_n)
    slow = sma_series(closes, slow_n)
    if np.isnan(fast[-1]) or np.isnan(slow[-1]):
        return []

    price = float(closes[-1])
    f_now, s_now = float(fast[-1]), float(slow[-1])
    gap = _pct(f_now, s_now)
    swing_hi, swing_lo = _swing_levels(ohlcv)

    if f_now < s_now:
        long_levels = [
            PriceLevel(f"突破近20根高点", swing_hi, ">="),
            PriceLevel(f"站稳慢均线 SMA{slow_n}", s_now, ">="),
            _crossover_watch_level(f_now, s_now, price, bullish=True),
        ]
        short_levels = [
            PriceLevel(f"跌破近20根低点", swing_lo, "<="),
            PriceLevel(f"跌破快线 SMA{fast_n}", f_now, "<="),
        ]
        long_summary = f"现价 {_fmt_price(price)}，快线低于慢线 {abs(gap):.2f}%"
        short_summary = f"空头排列加深时关注跌破 {_fmt_price(swing_lo)}"
    else:
        long_levels = [
            PriceLevel(f"突破近20根高点", swing_hi, ">="),
            PriceLevel(f"回踩不破慢均线 SMA{slow_n}", s_now, ">="),
        ]
        short_levels = [
            PriceLevel(f"跌破近20根低点", swing_lo, "<="),
            PriceLevel(f"跌破快线 SMA{fast_n}", f_now, "<="),
            _crossover_watch_level(f_now, s_now, price, bullish=False),
        ]
        long_summary = f"现价 {_fmt_price(price)}，多头排列快线高于慢线 {gap:.2f}%"
        short_summary = f"死叉确认优先看跌破快线 {_fmt_price(f_now)}"

    return [
        _make_hint(side="long", title="做多时机", levels=long_levels, summary=long_summary, current_price=price),
        _make_hint(side="short", title="做空时机", levels=short_levels, summary=short_summary, current_price=price),
    ]


def _hints_rsi(ohlcv: list[list[float]], settings: Settings) -> list[TimingHint]:
    closes = closes_array(ohlcv)
    rsi_val = _last_rsi(closes, settings.strategy_rsi_period)
    if rsi_val is None:
        return []
    os_level = settings.strategy_rsi_oversold
    ob_level = settings.strategy_rsi_overbought
    price = float(closes[-1])
    swing_hi, swing_lo = _swing_levels(ohlcv)
    sma20 = sma_series(closes, 20)
    s20 = float(sma20[-1]) if sma20.size and not np.isnan(sma20[-1]) else price

    long_levels = [
        PriceLevel(f"策略超卖做多(RSI≤{os_level:.0f})", swing_lo, "~"),
        PriceLevel("反弹突破近20根高点", swing_hi, ">="),
        PriceLevel("站上 SMA20", s20, ">="),
    ]
    short_levels = [
        PriceLevel(f"策略超买做空(RSI≥{ob_level:.0f})", swing_hi, "~"),
        PriceLevel("跌破近20根低点", swing_lo, "<="),
        PriceLevel("跌破 SMA20", s20, "<="),
    ]
    long_summary = f"现价 {_fmt_price(price)}，RSI {rsi_val:.1f}"
    short_summary = f"阻力 {_fmt_price(swing_hi)}，支撑 {_fmt_price(swing_lo)}"

    return [
        _make_hint(side="long", title="做多时机", levels=long_levels, summary=long_summary, current_price=price),
        _make_hint(side="short", title="做空时机", levels=short_levels, summary=short_summary, current_price=price),
    ]


def _hints_macd(ohlcv: list[list[float]], settings: Settings) -> list[TimingHint]:
    closes = closes_array(ohlcv)
    x = macd_signal_last(
        closes,
        settings.strategy_fast,
        settings.strategy_slow,
        settings.strategy_macd_signal,
    )
    if x is None:
        return []
    _, _, macd_now, sig_now = x
    price = float(closes[-1])
    swing_hi, swing_lo = _swing_levels(ohlcv)
    ema_slow = ema_series(closes, settings.strategy_slow)
    slow_val = float(ema_slow[-1]) if not np.isnan(ema_slow[-1]) else swing_lo

    if macd_now <= sig_now:
        long_levels = [
            PriceLevel("MACD 金叉确认(柱体转正)", swing_hi, ">="),
            PriceLevel("突破近20根高点", swing_hi, ">="),
            PriceLevel(f"站上慢线 EMA{settings.strategy_slow}", slow_val, ">="),
        ]
        short_levels = [
            PriceLevel("跌破近20根低点", swing_lo, "<="),
        ]
        long_summary = f"现价 {_fmt_price(price)}，DIF 低于 DEA"
        short_summary = f"空头加速看 {_fmt_price(swing_lo)}"
    else:
        long_levels = [
            PriceLevel("突破近20根高点", swing_hi, ">="),
            PriceLevel(f"回踩 EMA{settings.strategy_slow} 不破", slow_val, ">="),
        ]
        short_levels = [
            PriceLevel("MACD 死叉确认(柱体转负)", swing_lo, "<="),
            PriceLevel("跌破近20根低点", swing_lo, "<="),
            PriceLevel(f"跌破 EMA{settings.strategy_slow}", slow_val, "<="),
        ]
        long_summary = f"现价 {_fmt_price(price)}，DIF 高于 DEA"
        short_summary = f"转弱先看 {_fmt_price(swing_lo)}"

    return [
        _make_hint(side="long", title="做多时机", levels=long_levels, summary=long_summary, current_price=price),
        _make_hint(side="short", title="做空时机", levels=short_levels, summary=short_summary, current_price=price),
    ]


def _hints_generic(ohlcv: list[list[float]], settings: Settings) -> list[TimingHint]:
    closes = closes_array(ohlcv)
    if closes.size < 30:
        return []
    price = float(closes[-1])
    swing_hi, swing_lo = _swing_levels(ohlcv)
    sma20 = sma_series(closes, 20)
    sma50 = sma_series(closes, 50)
    s20 = float(sma20[-1]) if not np.isnan(sma20[-1]) else price
    s50 = float(sma50[-1]) if not np.isnan(sma50[-1]) else price
    tf = settings.timeframe

    long_levels = [
        PriceLevel(f"突破近{tf}高点", swing_hi, ">="),
        PriceLevel("站上 SMA20", s20, ">="),
    ]
    short_levels = [
        PriceLevel(f"跌破近{tf}低点", swing_lo, "<="),
        PriceLevel("跌破 SMA20", s20, "<="),
    ]
    if s20 > s50:
        short_levels.append(PriceLevel("跌破 SMA50", s50, "<="))

    rsi_val = _last_rsi(closes, 14)
    long_summary = f"现价 {_fmt_price(price)}" + (f"，RSI {rsi_val:.1f}" if rsi_val is not None else "")
    short_summary = f"支撑 {_fmt_price(swing_lo)} / 阻力 {_fmt_price(swing_hi)}"

    return [
        _make_hint(side="long", title="做多时机", levels=long_levels, summary=long_summary, current_price=price),
        _make_hint(side="short", title="做空时机", levels=short_levels, summary=short_summary, current_price=price),
    ]


def build_watch_timing_hints(
    ohlcv: list[list[float]],
    settings: Settings,
    signal: LLMSignal,
) -> list[TimingHint]:
    """Return long/short timing suggestions when the current signal is hold/flat."""
    if signal.action not in (Action.HOLD, Action.FLAT):
        return []

    name = settings.strategy_name.lower()
    if settings.signal_source == "llm":
        return _hints_generic(ohlcv, settings)

    builders = {
        "sma_cross": _hints_sma_cross,
        "rsi": _hints_rsi,
        "rsi_adaptive": _hints_rsi,
        "macd": _hints_macd,
    }
    fn = builders.get(name)
    if fn is not None:
        hints = fn(ohlcv, settings)
        if hints:
            return hints
    return _hints_generic(ohlcv, settings)


def timing_hints_to_dicts(hints: list[TimingHint]) -> list[dict[str, str | float | list[dict[str, str | float]]]]:
    return [h.to_dict() for h in hints]
