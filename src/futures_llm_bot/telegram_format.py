"""Named Telegram message templates for trade notifications."""

from __future__ import annotations

from collections import defaultdict

from futures_llm_bot.config import Settings
from futures_llm_bot.schemas import LLMSignal

_ACTION_EMOJI = {
    "long": "▲",
    "short": "▼",
    "hold": "◆",
    "flat": "■",
}

# Keys: symbol, source, action, size_pct, confidence, reason, timeframe, dry_run, equity_usdt, emoji
TEMPLATES: dict[str, str] = {
    "default": (
        "{emoji} {symbol}\n"
        "[{source}] {action} {size_pct:.0f}%\n"
        "conf={confidence:.2f}\n"
        "{reason}\n"
        "TF={timeframe} dry_run={dry_run} equity={equity_usdt}"
    ),
    "compact": "{emoji} {symbol} {action} {confidence:.0f}% — {reason}",
    "oneline": "{emoji} {symbol} | {action} | {reason}",
    "html": (
        "{emoji} <b>{symbol}</b>\n"
        "[{source}] <code>{action}</code> {size_pct:.0f}%\n"
        "conf={confidence:.2f}\n"
        "{reason}"
    ),
}


def build_trade_context(settings: Settings, signal: LLMSignal, **kwargs: object) -> dict[str, object]:
    eq = kwargs.get("equity_usdt")
    eq_s = f"{float(eq):.4f}" if isinstance(eq, (int, float)) else str(eq or "")
    return {
        "symbol": settings.symbol,
        "source": kwargs.get("source", ""),
        "action": signal.action.value,
        "size_pct": float(signal.size_pct),
        "confidence": float(signal.confidence),
        "reason": signal.reason or "",
        "timeframe": settings.timeframe,
        "dry_run": str(settings.dry_run),
        "equity_usdt": eq_s,
        "emoji": _ACTION_EMOJI.get(signal.action.value, ""),
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
