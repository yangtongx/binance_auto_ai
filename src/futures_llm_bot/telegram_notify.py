"""Optional Telegram alerts (Bot API ``sendMessage``)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from futures_llm_bot.config import Settings
from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.telegram_format import format_trade_message

logger = logging.getLogger(__name__)

_last_error_notify_monotonic = 0.0
_ERROR_NOTIFY_COOLDOWN_SEC = 300.0


def telegram_configured(settings: Settings) -> bool:
    return bool(settings.telegram_bot_token.strip() and settings.telegram_chat_id.strip())


def should_notify_trade_signal(settings: Settings, signal: LLMSignal) -> bool:
    mode = settings.telegram_notify_signals
    if mode == "off":
        return False
    if mode == "all":
        return True
    return signal.action in (Action.LONG, Action.SHORT, Action.FLAT)


def send_telegram_message(settings: Settings, text: str, *, timeout_sec: float = 15.0) -> None:
    if not telegram_configured(settings):
        return
    token = settings.telegram_bot_token.strip()
    chat_id = settings.telegram_chat_id.strip()
    msg = text if len(text) <= 4000 else text[:3997] + "..."
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body: dict[str, str] = {"chat_id": chat_id, "text": msg}
    if settings.telegram_parse_mode:
        body["parse_mode"] = settings.telegram_parse_mode
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        out = json.loads(raw)
        if not out.get("ok"):
            logger.warning("telegram API not ok: %s", raw[:500])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        logger.warning("telegram send failed: %s", e)


def send_telegram_trade_signal(
    settings: Settings,
    signal: LLMSignal,
    *,
    source: str,
    equity_usdt: float | None = None,
) -> None:
    if not should_notify_trade_signal(settings, signal):
        return
    text = format_trade_message(settings, signal, source=source, equity_usdt=equity_usdt)
    send_telegram_message(settings, text)


def notify_bot_started(
    settings: Settings,
    *,
    symbols: list[str],
    strategy_label: str,
) -> None:
    if not settings.telegram_notify_startup or not telegram_configured(settings):
        return
    sym_text = ", ".join(symbols[:10])
    if len(symbols) > 10:
        sym_text += f" …(+{len(symbols) - 10})"
    text = (
        "🤖 futures-llm-bot 已启动\n"
        f"testnet={settings.binance_testnet} dry_run={settings.dry_run}\n"
        f"mode={settings.symbol_mode} signal={settings.signal_source} strategy={strategy_label}\n"
        f"symbols: {sym_text or settings.symbol}"
    )
    send_telegram_message(settings, text)


def notify_candidate_pool_refresh(settings: Settings, symbols: list[str]) -> None:
    if not settings.telegram_notify_pool_refresh or not telegram_configured(settings):
        return
    send_telegram_message(settings, "📋 候选池刷新\n" + ", ".join(symbols))


def notify_real_order(
    settings: Settings,
    *,
    symbol: str,
    signal: LLMSignal,
    source: str,
) -> None:
    if not settings.telegram_notify_orders or not telegram_configured(settings):
        return
    sym_settings = settings.model_copy(update={"symbol": symbol})
    base = format_trade_message(sym_settings, signal, source=source)
    send_telegram_message(settings, "✅ 实盘下单\n" + base)


def notify_tick_error(settings: Settings, message: str) -> None:
    global _last_error_notify_monotonic
    if not settings.telegram_notify_errors or not telegram_configured(settings):
        return
    now = time.monotonic()
    if now - _last_error_notify_monotonic < _ERROR_NOTIFY_COOLDOWN_SEC:
        return
    _last_error_notify_monotonic = now
    send_telegram_message(settings, "⚠️ tick 异常\n" + message[:1500])
