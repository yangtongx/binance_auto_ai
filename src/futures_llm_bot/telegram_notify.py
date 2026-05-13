"""Optional Telegram alerts (Bot API ``sendMessage``)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from futures_llm_bot.config import Settings
from futures_llm_bot.schemas import LLMSignal
from futures_llm_bot.telegram_format import format_trade_message

logger = logging.getLogger(__name__)


def telegram_configured(settings: Settings) -> bool:
    return bool(settings.telegram_bot_token.strip() and settings.telegram_chat_id.strip())


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
    text = format_trade_message(settings, signal, source=source, equity_usdt=equity_usdt)
    send_telegram_message(settings, text)
