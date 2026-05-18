from __future__ import annotations

import argparse
import logging
import signal
import sys
import textwrap
import time
from datetime import datetime, timezone

from futures_llm_bot.binance_kline_ws import BinanceUsdMKlineBuffer
from futures_llm_bot.binance_usdm import (
    build_exchange,
    execute_signal,
    fetch_futures_usdt_equity,
    format_account_context,
    resolve_account_hedged,
)
from futures_llm_bot.backtest.engine import Strategy
from futures_llm_bot.config import Settings
from futures_llm_bot import metrics
from futures_llm_bot.llm_strategy import llm_decide
from futures_llm_bot.strategy_factory import build_live_strategy, strategy_min_ohlcv_bars
from futures_llm_bot.observability import start_observability_background
from futures_llm_bot.risk import assess_signal
from futures_llm_bot.risk_metrics import aligned_log_return_correlation, var_tail_block_reason_from_ohlcv
from futures_llm_bot.schemas import Action
from futures_llm_bot.session_risk import SessionRisk
from futures_llm_bot.telegram_notify import send_telegram_trade_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_corr_log_counter = 0

_stop_requested = False


def _request_stop(signum: int, _frame: object) -> None:
    """Signal handler: ask the main loop to exit gracefully after the current tick."""
    global _stop_requested
    _stop_requested = True
    logger.info("received signal %s; stopping after current tick", signum)


def _strategy_log_label(settings: Settings) -> str:
    n = settings.strategy_name
    if n in ("sma_cross", "macd"):
        return f"{n}({settings.strategy_fast},{settings.strategy_slow})"
    if n in ("rsi",):
        return f"{n}(p={settings.strategy_rsi_period})"
    if n in ("bollinger", "bb"):
        return f"{n}(p={settings.strategy_bb_period})"
    if n in ("ichimoku", "ichi"):
        return (
            f"{n}({settings.strategy_ichimoku_tenkan},{settings.strategy_ichimoku_kijun},"
            f"{settings.strategy_ichimoku_senkou_b})"
        )
    if n in ("fibonacci", "fib"):
        return f"{n}(lb={settings.strategy_fib_lookback},{settings.strategy_fib_level})"
    if n in ("volume_profile", "vp"):
        return f"{n}(bars={settings.strategy_vp_bars})"
    if n in ("stochastic", "stoch"):
        return f"{n}(k={settings.strategy_stoch_k},d={settings.strategy_stoch_d})"
    if n in ("atr_breakout", "atr"):
        return f"{n}(p={settings.strategy_atr_period},m={settings.strategy_atr_mult})"
    if n == "ml":
        return f"{n}({settings.ml_backend},{settings.ml_torch_arch},w={settings.strategy_ml_window})"
    if n == "composite":
        return f"composite({settings.composite_mode}:{settings.composite_members})"
    if n == "rsi_adaptive":
        return f"rsi_adaptive(vol {settings.strategy_vol_window}/{settings.strategy_vol_ref_window})"
    if n == "rl_sb3":
        return f"rl_sb3(w={settings.rl_window})"
    return n


def _sleep_until_next_minute_close(buffer_sec: float = 2.0) -> None:
    now = time.time()
    next_close = int(now // 60) * 60 + 60
    sleep_s = max(0.0, next_close - now + buffer_sec)
    logger.info("sleep %.1fs until next 1m candle close (+buffer)", sleep_s)
    time.sleep(sleep_s)


def _klines_prompt(ex, settings: Settings, *, account_context: str) -> str:
    ohlcv = ex.fetch_ohlcv(settings.symbol, timeframe=settings.timeframe, limit=settings.klines_limit)
    rows = ["time,open,high,low,close,volume"]
    for ts, o, h, low, c, v in ohlcv[-30:]:
        t = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
        rows.append(f"{t},{o},{h},{low},{c},{v}")
    table = "\n".join(rows)
    return textwrap.dedent(
        f"""
        Symbol: {settings.symbol}
        Timeframe: {settings.timeframe}
        MAX_NOTIONAL_USDT (hard cap per leg / net exposure): {settings.max_notional_usdt}
        {account_context}

        Last candles (UTC, oldest->newest within sample):
        {table}
        Decide the next action for USDT-M perpetual. Prefer hold when uncertain.
        """
    ).strip()


def _ohlcv_fetch_limit(settings: Settings) -> int:
    if settings.signal_source == "strategy":
        return max(settings.klines_limit, strategy_min_ohlcv_bars(settings))
    return settings.klines_limit


def _tick(
    ex,
    settings: Settings,
    *,
    account_hedged: bool,
    session: SessionRisk,
    rule_strategy: Strategy | None,
    ws_buffer: BinanceUsdMKlineBuffer | None = None,
) -> None:
    metrics.record_tick_attempt()
    try:
        equity = fetch_futures_usdt_equity(ex)
        session.on_tick(current_usdt_equity=equity)
        session.warn_if_drawdown_near_limit(current_equity=equity)
        if rule_strategy is not None:
            need = _ohlcv_fetch_limit(settings)
            if ws_buffer is not None:
                ohlcv = ws_buffer.get_snapshot(need)
                if len(ohlcv) < need:
                    logger.warning("ws buffer short (%s<%s); REST fetch", len(ohlcv), need)
                    ohlcv = ex.fetch_ohlcv(
                        settings.symbol,
                        timeframe=settings.timeframe,
                        limit=need,
                    )
            else:
                ohlcv = ex.fetch_ohlcv(
                    settings.symbol,
                    timeframe=settings.timeframe,
                    limit=need,
                )
            signal = rule_strategy.on_bar(len(ohlcv) - 1, ohlcv)
            logger.info("strategy signal: %s", signal.model_dump())

            if (
                settings.risk_var_window > 0
                and settings.risk_var_block
                and signal.action in (Action.LONG, Action.SHORT)
            ):
                vmsg = var_tail_block_reason_from_ohlcv(
                    ohlcv,
                    window=settings.risk_var_window,
                    alpha=settings.risk_var_alpha,
                    tail_limit=settings.risk_var_tail_limit,
                )
                if vmsg:
                    logger.warning("risk VaR gate: %s", vmsg)
                    metrics.record_tick_risk_blocked()
                    return

            aux = settings.risk_corr_aux_symbol.strip()
            if aux and rule_strategy is not None:
                global _corr_log_counter
                _corr_log_counter += 1
                if _corr_log_counter % settings.risk_corr_log_every == 0:
                    try:
                        ob = ex.fetch_ohlcv(aux, timeframe=settings.timeframe, limit=min(500, len(ohlcv)))
                        rho = aligned_log_return_correlation(ohlcv, ob)
                        if rho == rho:
                            logger.info(
                                "risk log-return correlation %s vs %s (tail-aligned): %.4f",
                                settings.symbol,
                                aux,
                                rho,
                            )
                    except Exception as e:
                        logger.debug("aux correlation fetch failed: %s", e)

        else:
            account_ctx = format_account_context(ex, settings, account_hedged=account_hedged)
            prompt = _klines_prompt(ex, settings, account_context=account_ctx)
            t0 = time.perf_counter()
            try:
                signal = llm_decide(settings, prompt)
                metrics.record_llm_success(time.perf_counter() - t0)
            except Exception:
                metrics.record_llm_failure()
                raise
            logger.info("LLM signal: %s", signal.model_dump())

        src = "strategy" if rule_strategy is not None else "llm"
        send_telegram_trade_signal(settings, signal, source=src, equity_usdt=equity)

        decision = assess_signal(signal, settings.min_confidence)
        if not decision.allowed:
            logger.warning("risk blocked: %s", decision.message)
            metrics.record_tick_risk_blocked()
            return

        gate = session.block_reason_for(signal.action, current_equity=equity)
        if gate:
            logger.warning("session risk blocked: %s", gate)
            metrics.record_tick_risk_blocked()
            return

        execute_signal(
            ex,
            settings,
            signal,
            account_hedged=account_hedged,
            session=session,
            on_real_order=metrics.record_real_order,
        )
    except Exception as e:
        metrics.record_tick_failed(repr(e))
        raise
    else:
        metrics.record_tick_completed()


def run_loop(settings: Settings, *, once: bool = False) -> None:
    if settings.observability_port > 0:
        start_observability_background(settings.observability_host, settings.observability_port)
    ex = build_exchange(settings)
    ex.load_markets()
    try:
        account_hedged = resolve_account_hedged(ex, settings)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    session = SessionRisk(settings)
    rule_strategy: Strategy | None = None
    if settings.signal_source == "strategy":
        rule_strategy = build_live_strategy(settings)

    ws_buffer: BinanceUsdMKlineBuffer | None = None
    if settings.use_websocket:
        if settings.signal_source != "strategy":
            raise SystemExit("USE_WEBSOCKET=true is only supported with SIGNAL_SOURCE=strategy")
        ws_buffer = BinanceUsdMKlineBuffer(
            ex,
            symbol=settings.symbol,
            timeframe=settings.timeframe,
            testnet=settings.binance_testnet,
            reconnect_base_sec=settings.ws_reconnect_base_sec,
            reconnect_max_sec=settings.ws_reconnect_max_sec,
            reconnect_jitter=settings.ws_reconnect_jitter,
        )
        ws_buffer.seed_from_rest(limit=_ohlcv_fetch_limit(settings))
        ws_buffer.start()

    if not settings.binance_api_key or not settings.binance_api_secret:
        logger.warning(
            "BINANCE_API_KEY/SECRET missing — public market data works; balance/positions/orders need keys "
            "(Docker: ./secrets/binance_api_key + compose secrets, or set env vars; empty .env values block *_FILE)"
        )

    logger.info(
        "markets loaded; signal_source=%s symbol=%s testnet=%s dry_run=%s min_confidence=%s once=%s hedged=%s "
        "openai_timeout=%ss exchange_timeout=%sms max_trades/day=%s max_daily_loss=%s warn_ratio=%s "
        "observability=%s:%s strategy=%s",
        settings.signal_source,
        settings.symbol,
        settings.binance_testnet,
        settings.dry_run,
        settings.min_confidence,
        once,
        account_hedged,
        settings.openai_timeout_sec,
        settings.exchange_timeout_ms,
        settings.max_trades_per_day,
        settings.max_daily_loss_usdt,
        settings.daily_loss_warn_ratio,
        settings.observability_host,
        settings.observability_port,
        _strategy_log_label(settings) if rule_strategy is not None else "n/a",
    )

    try:
        while True:
            if _stop_requested:
                logger.info("stop requested; exiting before next tick")
                break
            if not once:
                _sleep_until_next_minute_close()
                if _stop_requested:
                    logger.info("stop requested during sleep; exiting")
                    break
            try:
                _tick(
                    ex,
                    settings,
                    account_hedged=account_hedged,
                    session=session,
                    rule_strategy=rule_strategy,
                    ws_buffer=ws_buffer,
                )
            except Exception:
                logger.exception("tick failed")

            if once:
                break
            time.sleep(1.0)
    finally:
        if ws_buffer is not None:
            ws_buffer.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Binance USDT-M perpetual bot: LLM or rule-based (SMA cross) signals → risk → execution.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick (no wait for next minute close) and exit.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Load settings and validate imports, then exit (no API calls to OpenAI/Binance).",
    )
    args = parser.parse_args()

    if args.smoke:
        settings = Settings()
        logger.info("smoke: settings OK symbol=%s", settings.symbol)
        __import__("futures_llm_bot.execution", fromlist=["build_exchange"])
        __import__("futures_llm_bot.positions", fromlist=["fetch_position_legs"])
        __import__("futures_llm_bot.llm_strategy", fromlist=["llm_decide"])
        __import__("futures_llm_bot.strategy_factory", fromlist=["build_live_strategy"])
        logger.info("smoke: imports OK")
        return

    settings = Settings()
    if settings.signal_source == "llm" and not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required when SIGNAL_SOURCE=llm")
    if not settings.dry_run and (not settings.binance_api_key or not settings.binance_api_secret):
        raise SystemExit("BINANCE_API_KEY/SECRET required when DRY_RUN=false")

    # Graceful shutdown on container stop (SIGTERM) and Ctrl-C (SIGINT).
    signal.signal(signal.SIGINT, _request_stop)
    try:
        signal.signal(signal.SIGTERM, _request_stop)
    except (AttributeError, ValueError):
        pass  # SIGTERM unavailable on some platforms / non-main threads

    try:
        run_loop(settings, once=args.once)
    except KeyboardInterrupt:
        logger.info("stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
