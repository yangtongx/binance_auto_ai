"""Telegram 通知：启动、下单、候选池刷新、报错（由 TELEGRAM_NOTIFY_* 开关控制）。"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from binance_auto_ai.config import Settings
from binance_auto_ai.schemas import Action, LLMSignal
from binance_auto_ai.telegram_format import SEPARATOR, format_trade_message, short_symbol

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


def _format_symbol_list(symbols: list[str], *, max_shown: int = 10) -> str:
    shown = [f"• {short_symbol(s)}" for s in symbols[:max_shown]]
    extra = len(symbols) - max_shown
    if extra > 0:
        shown.append(f"… 还有 {extra} 个")
    return "\n".join(shown) if shown else "—"


def notify_bot_started(
    settings: Settings,
    *,
    symbols: list[str],
    strategy_label: str,
) -> None:
    if not settings.telegram_notify_startup or not telegram_configured(settings):
        return
    mode_label = "模拟" if settings.dry_run else "实盘"
    net_label = "testnet" if settings.binance_testnet else "mainnet"
    text = (
        f"🚀 binance-auto-ai 已启动\n"
        f"{SEPARATOR}\n"
        f"模式  {settings.symbol_mode} · {mode_label}\n"
        f"信号  {settings.signal_source} · {strategy_label}\n"
        f"环境  {net_label} · {settings.timeframe}\n"
        f"{SEPARATOR}\n"
        f"候选池 ({len(symbols)})\n"
        f"{_format_symbol_list(symbols)}"
    )
    send_telegram_message(settings, text)


def notify_candidate_pool_refresh(settings: Settings, symbols: list[str]) -> None:
    if not settings.telegram_notify_pool_refresh or not telegram_configured(settings):
        return
    text = (
        f"📋 候选池刷新 ({len(symbols)})\n"
        f"{SEPARATOR}\n"
        f"{_format_symbol_list(symbols)}"
    )
    send_telegram_message(settings, text)


def notify_real_order(
    settings: Settings,
    *,
    symbol: str,
    signal: LLMSignal,
    source: str,
    mark_price_usdt: float | None = None,
) -> None:
    if not settings.telegram_notify_orders or not telegram_configured(settings):
        return
    sym_settings = settings.model_copy(update={"symbol": symbol})
    base = format_trade_message(sym_settings, signal, source=source)
    price_line = ""
    if mark_price_usdt is not None and mark_price_usdt > 0:
        price_line = f"\n价格  {mark_price_usdt:.6g} USDT"
    send_telegram_message(settings, f"✅ 实盘下单\n{SEPARATOR}\n{base}{price_line}")


def notify_tick_error(settings: Settings, message: str) -> None:
    global _last_error_notify_monotonic
    if not settings.telegram_notify_errors or not telegram_configured(settings):
        return
    now = time.monotonic()
    if now - _last_error_notify_monotonic < _ERROR_NOTIFY_COOLDOWN_SEC:
        return
    _last_error_notify_monotonic = now
    text = f"⚠️ tick 异常\n{SEPARATOR}\n{message[:1500]}"
    send_telegram_message(settings, text)


def notify_coinglass_alert(settings: Settings, text: str) -> None:
    if not settings.telegram_notify_cg_alerts or not telegram_configured(settings):
        return
    send_telegram_message(settings, text)
