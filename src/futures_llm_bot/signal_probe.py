"""On-demand signal for a single symbol (analysis only, no orders)."""

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import ccxt

from futures_llm_bot.binance_usdm import build_exchange, format_account_context, resolve_account_hedged
from futures_llm_bot.config import Settings
from futures_llm_bot.exchange_env import load_binance_usdm_markets
from futures_llm_bot.llm_strategy import llm_decide
from futures_llm_bot.risk import assess_signal
from futures_llm_bot.schemas import Action, LLMSignal
from futures_llm_bot.strategy_factory import build_live_strategy, strategy_min_ohlcv_bars
from futures_llm_bot.symbol_input import resolve_usdm_symbol
from futures_llm_bot.symbol_picker import evaluate_candidate_signals
from futures_llm_bot.telegram_format import _ACTION_CN
from futures_llm_bot.time_display import format_iso_to_display, utc_now_iso

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalProbeResult:
    ok: bool
    symbol_input: str
    symbol: str = ""
    action: str = ""
    action_cn: str = ""
    advice: str = ""
    advice_cn: str = ""
    confidence: float = 0.0
    size_pct: float = 0.0
    reason: str = ""
    source: str = ""
    strategy_label: str = ""
    timeframe: str = ""
    at: str = ""
    at_display: str = ""
    would_trade: bool = False
    risk_message: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "symbol_input": self.symbol_input,
            "symbol": self.symbol,
            "action": self.action,
            "action_cn": self.action_cn,
            "advice": self.advice,
            "advice_cn": self.advice_cn,
            "confidence": self.confidence,
            "size_pct": self.size_pct,
            "reason": self.reason,
            "source": self.source,
            "strategy_label": self.strategy_label,
            "timeframe": self.timeframe,
            "at": self.at,
            "at_display": self.at_display,
            "would_trade": self.would_trade,
            "risk_message": self.risk_message,
            "error": self.error,
            "signal": {
                "action": self.action,
                "size_pct": self.size_pct,
                "confidence": self.confidence,
                "reason": self.reason,
            }
            if self.ok
            else None,
        }


def advice_from_action(action: Action) -> tuple[str, str]:
    """Map to user-facing long / short / watch (观望)."""
    if action == Action.LONG:
        return "long", "做多"
    if action == Action.SHORT:
        return "short", "做空"
    return "watch", "观望"


def build_klines_prompt(
    ex: ccxt.binanceusdm,
    settings: Settings,
    *,
    account_context: str = "",
) -> str:
    ohlcv = ex.fetch_ohlcv(settings.symbol, timeframe=settings.timeframe, limit=settings.klines_limit)
    rows = ["time,open,high,low,close,volume"]
    for ts, o, h, low, c, v in ohlcv[-30:]:
        t = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
        rows.append(f"{t},{o},{h},{low},{c},{v}")
    table = "\n".join(rows)
    ctx = account_context.strip() or "（诊币模式：未附加账户持仓上下文）"
    return textwrap.dedent(
        f"""
        Symbol: {settings.symbol}
        Timeframe: {settings.timeframe}
        MAX_NOTIONAL_USDT (hard cap per leg / net exposure): {settings.max_notional_usdt}
        {ctx}

        Last candles (UTC, oldest->newest within sample):
        {table}
        Decide the next action for USDT-M perpetual. Prefer hold when uncertain.
        """
    ).strip()


def _ohlcv_fetch_limit(settings: Settings) -> int:
    if settings.signal_source == "strategy":
        return max(settings.klines_limit, strategy_min_ohlcv_bars(settings))
    return settings.klines_limit


def _strategy_label(settings: Settings) -> str:
    if settings.signal_source == "llm":
        return "llm"
    return settings.strategy_name


def _result_from_signal(
    *,
    symbol_input: str,
    symbol: str,
    signal: LLMSignal,
    settings: Settings,
    source: str,
) -> SignalProbeResult:
    action = signal.action.value
    action_cn = _ACTION_CN.get(action, action)
    advice, advice_cn = advice_from_action(signal.action)
    decision = assess_signal(signal, settings.min_confidence)
    would_trade = decision.allowed and signal.action in (Action.LONG, Action.SHORT)
    at = utc_now_iso()
    return SignalProbeResult(
        ok=True,
        symbol_input=symbol_input,
        symbol=symbol,
        action=action,
        action_cn=action_cn,
        advice=advice,
        advice_cn=advice_cn,
        confidence=float(signal.confidence),
        size_pct=float(signal.size_pct),
        reason=signal.reason or "",
        source=source,
        strategy_label=_strategy_label(settings),
        timeframe=settings.timeframe,
        at=at,
        at_display=format_iso_to_display(at, compact=True),
        would_trade=would_trade,
        risk_message="" if would_trade else (decision.message or ""),
    )


def evaluate_symbol_signal(
    settings: Settings,
    symbol_input: str,
    *,
    ex: ccxt.binanceusdm | None = None,
) -> SignalProbeResult:
    """Fetch latest bar(s) and return long/short/watch without placing orders."""
    raw = str(symbol_input or "").strip()
    if not raw:
        return SignalProbeResult(ok=False, symbol_input=raw, error="请输入币种或交易对")

    own_ex = ex is None
    try:
        if ex is None:
            ex = build_exchange(settings)
            load_binance_usdm_markets(ex)
        symbol = resolve_usdm_symbol(ex, raw)
        run_settings = settings.model_copy(update={"symbol": symbol})

        if settings.signal_source == "strategy":
            strategy = build_live_strategy(run_settings)
            need = _ohlcv_fetch_limit(run_settings)
            signals = evaluate_candidate_signals(ex, run_settings, strategy, [symbol], ohlcv_limit=need)
            signal = signals[symbol]
            return _result_from_signal(
                symbol_input=raw,
                symbol=symbol,
                signal=signal,
                settings=run_settings,
                source="strategy",
            )

        try:
            account_hedged = resolve_account_hedged(ex, run_settings)
        except ValueError:
            account_hedged = False
        account_ctx = format_account_context(ex, run_settings, account_hedged=account_hedged)
        prompt = build_klines_prompt(ex, run_settings, account_context=account_ctx)
        signal = llm_decide(run_settings, prompt)
        return _result_from_signal(
            symbol_input=raw,
            symbol=symbol,
            signal=signal,
            settings=run_settings,
            source="llm",
        )
    except ccxt.BaseError as e:
        logger.warning("signal probe exchange error for %s: %s", raw, e)
        return SignalProbeResult(ok=False, symbol_input=raw, error=f"交易所请求失败: {e}")
    except Exception as e:
        logger.warning("signal probe failed for %s: %s", raw, e)
        return SignalProbeResult(ok=False, symbol_input=raw, error=str(e))
    finally:
        if own_ex and ex is not None:
            try:
                ex.close()
            except Exception:
                pass
