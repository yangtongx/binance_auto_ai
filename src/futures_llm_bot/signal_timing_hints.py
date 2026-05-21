"""When the probe says watch/hold, suggest what would trigger long or short."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from futures_llm_bot.backtest.indicators import closes_array, macd_signal_last, rsi_wilder_series, sma_series
from futures_llm_bot.config import Settings
from futures_llm_bot.schemas import Action, LLMSignal


@dataclass(frozen=True)
class TimingHint:
    side: str
    title: str
    summary: str
    trigger: str

    def to_dict(self) -> dict[str, str]:
        return {
            "side": self.side,
            "title": self.title,
            "summary": self.summary,
            "trigger": self.trigger,
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
    tf = settings.timeframe
    swing_hi, swing_lo = _swing_levels(ohlcv)

    if f_now < s_now:
        long_trigger = (
            f"快均线({fast_n})上穿慢均线({slow_n})形成金叉（当前快线低于慢线约 {abs(gap):.2f}%）"
        )
        long_summary = (
            f"价格需温和上行推动快线靠近慢线；可参考突破近期高点 {_fmt_price(swing_hi)} 或站稳慢线 {_fmt_price(s_now)}"
        )
        short_trigger = (
            f"快线继续低于慢线且价格跌破近期低点 {_fmt_price(swing_lo)}，空头排列加深"
        )
        short_summary = f"或反弹至慢线 {_fmt_price(s_now)} 附近受阻后回落（{tf} 死叉确认更稳）"
    else:
        long_trigger = (
            f"快线高于慢线时，回踩慢线 {_fmt_price(s_now)} 不破并再度走强，或突破高点 {_fmt_price(swing_hi)}"
        )
        long_summary = f"当前多头排列，快线高于慢线约 {gap:.2f}%"
        short_trigger = (
            f"快均线({fast_n})下穿慢均线({slow_n})形成死叉（当前快线高于慢线约 {gap:.2f}%）"
        )
        short_summary = f"价格走弱使快线回落跌破慢线；跌破低点 {_fmt_price(swing_lo)} 可视为辅助确认"

    return [
        TimingHint("long", "做多时机", long_summary, long_trigger),
        TimingHint("short", "做空时机", short_summary, short_trigger),
    ]


def _hints_rsi(ohlcv: list[list[float]], settings: Settings) -> list[TimingHint]:
    closes = closes_array(ohlcv)
    rsi_val = _last_rsi(closes, settings.strategy_rsi_period)
    if rsi_val is None:
        return []
    os_level = settings.strategy_rsi_oversold
    ob_level = settings.strategy_rsi_overbought
    swing_hi, swing_lo = _swing_levels(ohlcv)

    if rsi_val < (os_level + ob_level) / 2:
        long_trigger = f"RSI 跌至超卖区 ≤ {os_level:.0f}（当前 {rsi_val:.1f}）"
        long_summary = f"策略将倾向抄底做多；也可关注 RSI 从低位拐头向上同时价格守住 {_fmt_price(swing_lo)}"
        short_trigger = f"RSI 升至超买区 ≥ {ob_level:.0f} 且价格接近阻力 {_fmt_price(swing_hi)}"
        short_summary = "均值回归策略在超买区寻找做空机会"
    else:
        long_trigger = f"RSI 回落至超卖区 ≤ {os_level:.0f}（当前 {rsi_val:.1f}）"
        long_summary = f"或价格回调至支撑 {_fmt_price(swing_lo)} 且 RSI 拐头向上"
        short_trigger = f"RSI 进入超买 ≥ {ob_level:.0f}（当前 {rsi_val:.1f}）"
        short_summary = f"策略将倾向高抛做空；跌破 {_fmt_price(swing_lo)} 则观望转弱"

    return [
        TimingHint("long", "做多时机", long_summary, long_trigger),
        TimingHint("short", "做空时机", short_summary, short_trigger),
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
    macd_prev, sig_prev, macd_now, sig_now = x
    swing_hi, swing_lo = _swing_levels(ohlcv)
    hist = macd_now - sig_now

    if macd_now <= sig_now:
        long_trigger = "MACD 柱体由负转正（DIF 上穿 DEA）"
        long_summary = (
            f"当前 DIF 低于信号线（柱体 {hist:.6f}）；放量突破 {_fmt_price(swing_hi)} 可加强做多确认"
        )
        short_trigger = f"DIF 远离 DEA 向下且价格跌破 {_fmt_price(swing_lo)}"
        short_summary = "空头动能增强时策略倾向追空"
    else:
        long_trigger = f"MACD 维持多头且价格站稳 {_fmt_price(swing_hi)} 上方"
        long_summary = f"柱体 {hist:.6f}，回踩不破可继续持有思路"
        short_trigger = "MACD 柱体由正转负（DIF 下穿 DEA）"
        short_summary = f"或价格跌破慢线支撑 {_fmt_price(swing_lo)}"

    return [
        TimingHint("long", "做多时机", long_summary, long_trigger),
        TimingHint("short", "做空时机", short_summary, short_trigger),
    ]


def _hints_generic(ohlcv: list[list[float]], settings: Settings) -> list[TimingHint]:
    closes = closes_array(ohlcv)
    if closes.size < 30:
        return []
    price = float(closes[-1])
    rsi_val = _last_rsi(closes, 14)
    sma20 = sma_series(closes, 20)
    sma50 = sma_series(closes, 50)
    swing_hi, swing_lo = _swing_levels(ohlcv)
    tf = settings.timeframe

    rsi_long = (
        f"RSI 进入超卖区（<30，当前 {rsi_val:.1f}）并拐头向上"
        if rsi_val is not None
        else "RSI 超卖拐头"
    )
    rsi_short = (
        f"RSI 进入超买区（>70，当前 {rsi_val:.1f}）并拐头向下"
        if rsi_val is not None
        else "RSI 超买拐头"
    )

    s20 = float(sma20[-1]) if not np.isnan(sma20[-1]) else None
    s50 = float(sma50[-1]) if not np.isnan(sma50[-1]) else None

    long_parts = [rsi_long, f"突破近 {tf} 高点 {_fmt_price(swing_hi)}"]
    short_parts = [rsi_short, f"跌破近 {tf} 低点 {_fmt_price(swing_lo)}"]

    if s20 is not None and price < s20:
        long_parts.append(f"价格 {_fmt_price(price)} 重新站上 SMA20 {_fmt_price(s20)}")
    if s50 is not None and s20 is not None and s20 > s50:
        short_parts.append(f"价格跌破 SMA20 {_fmt_price(s20)} 且 SMA20 下穿 SMA50")

    return [
        TimingHint("long", "做多时机", "；".join(long_parts[:2]), long_parts[0]),
        TimingHint("short", "做空时机", "；".join(short_parts[:2]), short_parts[0]),
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


def timing_hints_to_dicts(hints: list[TimingHint]) -> list[dict[str, str]]:
    return [h.to_dict() for h in hints]
