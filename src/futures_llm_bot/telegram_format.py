"""Telegram 消息模板：做多/做空/观望中文文案与 emoji。"""

from __future__ import annotations

from collections import defaultdict

from futures_llm_bot.config import Settings
from futures_llm_bot.schemas import LLMSignal

_ACTION_EMOJI = {
    "long": "🟢",
    "short": "🔴",
    "hold": "⚪",
    "flat": "⚫",
}

_ACTION_CN = {
    "long": "做多",
    "short": "做空",
    "hold": "观望",
    "flat": "平仓",
}

SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"

# 模板占位符：symbol, short_symbol, source, action, action_cn, size_pct, confidence, reason,
#             timeframe, dry_run, mode_label, equity_usdt, equity_line, emoji, separator
TEMPLATES: dict[str, str] = {
    "default": (
        "{emoji} {action_cn} · {short_symbol}\n"
        "{separator}\n"
        "策略  {source} · {mode_label}\n"
        "仓位  {size_pct:.0f}% · 置信度 {confidence:.2f}\n"
        "周期  {timeframe}{equity_line}\n"
        "原因  {reason}"
    ),
    "compact": "{emoji} {short_symbol} {action_cn} {confidence:.0%} — {reason}",
    "oneline": "{emoji} {short_symbol} | {action_cn} | {reason}",
    "html": (
        "{emoji} <b>{action_cn}</b> · <b>{short_symbol}</b>\n"
        "<code>{source}</code> · {mode_label}\n"
        "仓位 {size_pct:.0f}% · 置信度 {confidence:.2f}\n"
        "{reason}"
    ),
}


def short_symbol(symbol: str) -> str:
    """``DOGE/USDT:USDT`` -> ``DOGE/USDT``."""
    return symbol.split(":", 1)[0] if symbol else symbol


def build_trade_context(settings: Settings, signal: LLMSignal, **kwargs: object) -> dict[str, object]:
    eq = kwargs.get("equity_usdt")
    eq_s = f"{float(eq):.2f}" if isinstance(eq, (int, float)) else str(eq or "")
    eq_line = f" · 权益 {eq_s} USDT" if eq_s else ""
    mode_label = "模拟" if settings.dry_run else "实盘"
    action_value = signal.action.value
    return {
        "symbol": settings.symbol,
        "short_symbol": short_symbol(settings.symbol),
        "source": kwargs.get("source", ""),
        "action": action_value,
        "action_cn": _ACTION_CN.get(action_value, action_value),
        "size_pct": float(signal.size_pct),
        "confidence": float(signal.confidence),
        "reason": signal.reason or "—",
        "timeframe": settings.timeframe,
        "dry_run": str(settings.dry_run),
        "mode_label": mode_label,
        "equity_usdt": eq_s,
        "equity_line": eq_line,
        "emoji": _ACTION_EMOJI.get(action_value, ""),
        "separator": SEPARATOR,
    }


def format_trade_message(settings: Settings, signal: LLMSignal, **kwargs: object) -> str:
    ctx_raw = build_trade_context(settings, signal, **kwargs)
    pad: defaultdict[str, object] = defaultdict(str)
    pad.update(ctx_raw)
    custom = settings.telegram_message_template.strip()
    if custom:
        tpl = custom
    else:
        key = settings.telegram_template.strip().lower()
        tpl = TEMPLATES.get(key, TEMPLATES["default"])
    return str(tpl.format_map(pad))
