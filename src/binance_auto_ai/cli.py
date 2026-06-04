"""主程序入口：每分钟 tick、signal_pick 选币、风控、下单与监控面板。"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import textwrap
import time
from datetime import datetime, timezone

from binance_auto_ai.binance_kline_ws import BinanceUsdMKlineBuffer
from binance_auto_ai.binance_usdm import (
    build_exchange,
    execute_signal,
    fetch_futures_usdt_balance,
    fetch_futures_usdt_equity,
    format_account_context,
    resolve_account_hedged,
    verify_position_mode_alignment,
)
from binance_auto_ai.active_exit import ExitTracker, held_exit_signal
from binance_auto_ai.backtest.engine import Strategy
from binance_auto_ai.config import Settings
from binance_auto_ai.constants import NET_POSITION_EPS_CONTRACTS
from binance_auto_ai.ohlcv_utils import drop_incomplete_last_candle
from binance_auto_ai import dashboard_state, metrics
from binance_auto_ai.llm_strategy import llm_decide
from binance_auto_ai.strategy_factory import build_live_strategy, strategy_min_ohlcv_bars
from binance_auto_ai.observability import start_observability_background
from binance_auto_ai.risk import assess_signal
from binance_auto_ai.risk_metrics import aligned_log_return_correlation, var_tail_block_reason_from_ohlcv
from binance_auto_ai.schemas import Action
from binance_auto_ai.session_risk import SessionRisk
from binance_auto_ai.positions import fetch_position_legs
from binance_auto_ai.coinglass_entry import entry_cg_enabled, fetch_entry_contexts, pick_best_with_coinglass
from binance_auto_ai.symbol_picker import (
    evaluate_candidate_signals,
    log_candidate_signals,
    pick_best_directional,
    plan_signal_pick_trades,
    resolve_held_symbol,
)
from binance_auto_ai.coinglass_alerts import CoinglassAlertWatcher, list_held_symbols
from binance_auto_ai.coinglass_context import coinglass_llm_appendix, refresh_coinglass_market_views
from binance_auto_ai.symbol_universe import CandidatePool
from binance_auto_ai.telegram_notify import (
    notify_bot_started,
    notify_candidate_pool_refresh,
    notify_real_order,
    notify_tick_error,
    send_telegram_trade_signal,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_corr_log_counter = 0
_non_whitelist_flat_dry_run_notified: set[str] = set()

_stop_requested = False


def _request_stop(signum: int, _frame: object) -> None:
    """信号处理：当前 tick 结束后优雅退出主循环。"""
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


def _sleep_until_next_candle_close(timeframe: str, buffer_sec: float = 2.0) -> None:
    """对齐到下一根 ``TIMEFRAME`` K 线收盘后再跑策略（避免未收盘 K 重复触发交叉）。"""
    from binance_auto_ai.ohlcv_utils import timeframe_to_seconds

    now = time.time()
    tf_sec = timeframe_to_seconds(timeframe) or 60
    next_close = int(now // tf_sec) * tf_sec + tf_sec
    sleep_s = max(0.0, next_close - now + buffer_sec)
    logger.info("sleep %.1fs until next %s candle close (+buffer)", sleep_s, timeframe)
    time.sleep(sleep_s)


def _klines_prompt(
    ex,
    settings: Settings,
    *,
    account_context: str,
    coinglass: object | None = None,
) -> str:
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
        {coinglass_llm_appendix(coinglass, settings, settings.symbol) if coinglass else ""}
        """
    ).strip()


def _ohlcv_fetch_limit(settings: Settings) -> int:
    if settings.signal_source == "strategy":
        return max(settings.klines_limit, strategy_min_ohlcv_bars(settings))
    return settings.klines_limit


def _run_trade_step(
    ex,
    settings: Settings,
    signal,
    *,
    symbol: str,
    account_hedged: bool,
    equity: float | None,
    available_margin: float | None,
    session: SessionRisk,
    src: str,
) -> bool:
    """风控 + 会话限额 + 执行下单；被拦截时返回 False。"""
    send_telegram_trade_signal(settings.model_copy(update={"symbol": symbol}), signal, source=src, equity_usdt=equity)
    decision = assess_signal(signal, settings.min_confidence)
    if not decision.allowed:
        logger.warning("risk blocked (%s): %s", symbol, decision.message)
        metrics.record_tick_risk_blocked()
        dashboard_state.append_decision(
            symbol=symbol,
            signal=signal,
            source=src,
            outcome="risk_blocked",
            detail=decision.message or "",
        )
        return False
    gate = session.block_reason_for(signal.action, current_equity=equity)
    if gate:
        logger.warning("session risk blocked (%s): %s", symbol, gate)
        metrics.record_tick_risk_blocked()
        dashboard_state.append_decision(
            symbol=symbol,
            signal=signal,
            source=src,
            outcome="session_blocked",
            detail=gate,
        )
        return False
    def _on_real_order(mark_price_usdt: float) -> None:
        metrics.record_real_order()
        notify_real_order(
            settings,
            symbol=symbol,
            signal=signal,
            source=src,
            mark_price_usdt=mark_price_usdt,
        )

    execute_signal(
        ex,
        settings,
        signal,
        account_hedged=account_hedged,
        symbol=symbol,
        equity_usdt=equity,
        available_margin_usdt=available_margin,
        session=session,
        on_real_order=_on_real_order,
    )
    dashboard_state.append_decision(
        symbol=symbol,
        signal=signal,
        source=src,
        outcome="dry_run" if settings.dry_run else "executed",
        detail=signal.action.value,
    )
    return True


def _maybe_exit_held(
    ex,
    settings: Settings,
    *,
    symbol: str,
    account_hedged: bool,
    equity: float | None,
    available_margin: float | None,
    session: SessionRisk,
    exit_tracker: ExitTracker | None,
    coinglass: object | None = None,
) -> bool:
    """主动离场：触发任一止损/止盈/移动止盈/超时/CoinGlass 规则则强制 FLAT，返回 True 表示本轮已离场。"""
    if exit_tracker is None:
        return False
    forced = held_exit_signal(ex, settings, symbol, exit_tracker, coinglass=coinglass)
    if forced is None:
        return False
    logger.info("active exit %s: %s", symbol, forced.reason)
    _run_trade_step(
        ex,
        settings,
        forced,
        symbol=symbol,
        account_hedged=account_hedged,
        equity=equity,
        available_margin=available_margin,
        session=session,
        src="exit",
    )
    return True


def _tick_signal_pick(
    ex,
    settings: Settings,
    *,
    account_hedged: bool,
    session: SessionRisk,
    rule_strategy: Strategy,
    candidate_pool: CandidatePool,
    exit_tracker: ExitTracker | None = None,
    exit_coinglass: object | None = None,
) -> None:
    """多币候选池模式：扫描信号 → 选最强 → 规划平仓/换币/开仓步骤并执行。"""
    candidates = candidate_pool.symbols()
    need = _ohlcv_fetch_limit(settings)
    signals = evaluate_candidate_signals(ex, settings, rule_strategy, candidates, ohlcv_limit=need)
    held, held_in_whitelist = resolve_held_symbol(ex, candidates, dry_run=settings.dry_run)
    if exit_tracker is not None and held is not None and held_in_whitelist:
        equity, available_margin = fetch_futures_usdt_balance(ex)
        session.on_tick(current_usdt_equity=equity)
        if _maybe_exit_held(
            ex,
            settings,
            symbol=held,
            account_hedged=account_hedged,
            equity=equity,
            available_margin=available_margin,
            session=session,
            exit_tracker=exit_tracker,
            coinglass=exit_coinglass,
        ):
            return
    entry_contexts = fetch_entry_contexts(
        ex, exit_coinglass, settings, candidates, signals  # type: ignore[arg-type]
    )
    if entry_cg_enabled(settings):
        pick = pick_best_with_coinglass(
            signals,
            candidates_order=candidates,
            min_confidence=settings.min_confidence,
            contexts=entry_contexts,
            settings=settings,
        )
    else:
        pick = pick_best_directional(
            signals, candidates_order=candidates, min_confidence=settings.min_confidence
        )
    log_candidate_signals(candidates, signals, pick=pick)
    dashboard_state.set_candidates(candidates)
    dashboard_state.set_signals(signals)
    if pick is not None:
        dashboard_state.note_pick(symbol=pick.symbol, signal=pick.signal, score=pick.score)
    cg_syms: list[str] = []
    if held:
        cg_syms.append(held)
    if pick is not None and pick.symbol not in cg_syms:
        cg_syms.append(pick.symbol)
    refresh_coinglass_market_views(ex, exit_coinglass, settings, cg_syms)
    held_position_side: Action | None = None
    if held is not None:
        net = fetch_position_legs(ex, held, dry_run=settings.dry_run).signed_net()
        if net > NET_POSITION_EPS_CONTRACTS:
            held_position_side = Action.LONG
        elif net < -NET_POSITION_EPS_CONTRACTS:
            held_position_side = Action.SHORT
    steps = plan_signal_pick_trades(
        signals,
        candidates=candidates,
        held_symbol=held,
        held_outside_whitelist=held is not None and not held_in_whitelist,
        min_confidence=settings.min_confidence,
        rotation_hysteresis=settings.symbol_rotation_hysteresis,
        held_position_side=held_position_side,
        preferred_pick=pick,
        entry_contexts=entry_contexts if entry_cg_enabled(settings) else None,
        settings=settings if entry_cg_enabled(settings) else None,
    )
    if not steps:
        logger.info("signal_pick: no trade steps this tick")
        return
    equity, available_margin = fetch_futures_usdt_balance(ex)
    session.on_tick(current_usdt_equity=equity)
    session.warn_if_drawdown_near_limit(current_equity=equity)
    for step in steps:
        if "non-whitelist" in (step.signal.reason or ""):
            if settings.dry_run:
                if step.symbol in _non_whitelist_flat_dry_run_notified:
                    continue
                _non_whitelist_flat_dry_run_notified.add(step.symbol)
                logger.warning(
                    "Account still has %s outside the candidate pool; dry_run does not send orders. "
                    "Close it on Binance, or set DRY_RUN=false to let the bot FLAT once.",
                    step.symbol,
                )
                continue
        logger.info("signal_pick execute: %s %s", step.symbol, step.signal.model_dump())
        _run_trade_step(
            ex,
            settings,
            step.signal,
            symbol=step.symbol,
            account_hedged=account_hedged,
            equity=equity,
            available_margin=available_margin,
            session=session,
            src="strategy",
        )


def _tick(
    ex,
    settings: Settings,
    *,
    account_hedged: bool,
    session: SessionRisk,
    rule_strategy: Strategy | None,
    ws_buffer: BinanceUsdMKlineBuffer | None = None,
    candidate_pool: CandidatePool | None = None,
    exit_tracker: ExitTracker | None = None,
    exit_coinglass: object | None = None,
) -> None:
    """单次 tick：signal_pick 或单币 LLM/规则策略，最后刷新面板状态。"""
    metrics.record_tick_attempt()
    try:
        if settings.symbol_mode == "signal_pick":
            if rule_strategy is None:
                raise RuntimeError("signal_pick requires SIGNAL_SOURCE=strategy")
            if candidate_pool is None:
                raise RuntimeError("signal_pick requires candidate_pool")
            _tick_signal_pick(
                ex,
                settings,
                account_hedged=account_hedged,
                session=session,
                rule_strategy=rule_strategy,
                candidate_pool=candidate_pool,
                exit_tracker=exit_tracker,
                exit_coinglass=exit_coinglass,
            )
            return

        equity, available_margin = fetch_futures_usdt_balance(ex)
        session.on_tick(current_usdt_equity=equity)
        session.warn_if_drawdown_near_limit(current_equity=equity)
        # 主动离场优先于策略信号：触发即强制平仓并跳过本轮策略
        if _maybe_exit_held(
            ex,
            settings,
            symbol=settings.symbol,
            account_hedged=account_hedged,
            equity=equity,
            available_margin=available_margin,
            session=session,
            exit_tracker=exit_tracker,
            coinglass=exit_coinglass,
        ):
            metrics.record_tick_completed()
            return
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
            closed = drop_incomplete_last_candle(ohlcv, settings.timeframe)
            if hasattr(rule_strategy, "reset"):
                rule_strategy.reset()
            signal = rule_strategy.on_bar(max(0, len(closed) - 1), closed)
            logger.info("strategy signal: %s", signal.model_dump())
            dashboard_state.set_candidates([settings.symbol])
            dashboard_state.set_signals({settings.symbol: signal})

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

            refresh_coinglass_market_views(ex, exit_coinglass, settings, [settings.symbol])

        else:
            account_ctx = format_account_context(ex, settings, account_hedged=account_hedged)
            refresh_coinglass_market_views(ex, exit_coinglass, settings, [settings.symbol])
            prompt = _klines_prompt(
                ex, settings, account_context=account_ctx, coinglass=exit_coinglass
            )
            t0 = time.perf_counter()
            try:
                signal = llm_decide(settings, prompt)
                metrics.record_llm_success(time.perf_counter() - t0)
            except Exception:
                metrics.record_llm_failure()
                raise
            logger.info("LLM signal: %s", signal.model_dump())
            dashboard_state.set_candidates([settings.symbol])
            dashboard_state.set_signals({settings.symbol: signal})

        src = "strategy" if rule_strategy is not None else "llm"
        _run_trade_step(
            ex,
            settings,
            signal,
            symbol=settings.symbol,
            account_hedged=account_hedged,
            equity=equity,
            available_margin=available_margin,
            session=session,
            src=src,
        )
    except Exception as e:
        metrics.record_tick_failed(repr(e))
        dashboard_state.append_event(f"tick failed: {e!r}")
        notify_tick_error(settings, repr(e))
        raise
    else:
        metrics.record_tick_completed()
    finally:
        try:
            dashboard_state.refresh_exchange(ex, settings, session)
        except Exception:
            logger.debug("dashboard refresh failed", exc_info=True)


def run_loop(settings: Settings, *, once: bool = False) -> None:
    """启动主循环：初始化交易所、候选池、策略，每分钟执行 _tick。"""
    if settings.observability_port > 0:
        start_observability_background(settings.observability_host, settings.observability_port)
    from binance_auto_ai.exchange_env import apply_symbol_leverage, load_binance_usdm_markets
    from binance_auto_ai.order_utils import warn_if_max_notional_below_minimum

    ex = build_exchange(settings)
    load_binance_usdm_markets(ex)
    coinglass_client = None
    if settings.coinglass_enabled():
        from binance_auto_ai.coinglass import build_coinglass_client

        coinglass_client = build_coinglass_client(settings)
    cg_alert_watcher: CoinglassAlertWatcher | None = None
    if settings.coinglass_alert_enabled():
        cg_alert_watcher = CoinglassAlertWatcher()
        logger.info(
            "coinglass alerts enabled: interval=%ss cooldown=%ss netflow_usd=%s balance_pct=%s whale_usd=%s",
            settings.coinglass_alert_interval_sec,
            settings.coinglass_alert_cooldown_sec,
            settings.coinglass_alert_netflow_usd,
            settings.coinglass_alert_exchange_balance_pct_1d,
            settings.coinglass_alert_whale_usd,
        )
    candidate_pool: CandidatePool | None = None
    if settings.symbol_mode == "signal_pick":
        candidate_pool = CandidatePool(settings, coinglass=coinglass_client)
        candidate_pool.refresh(ex)
        for sym in candidate_pool.symbols():
            apply_symbol_leverage(ex, settings, symbol=sym)
    else:
        apply_symbol_leverage(ex, settings)
    try:
        verify_position_mode_alignment(ex, settings)
        account_hedged = resolve_account_hedged(ex, settings)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    logger.info("position mode: %s (account_hedged=%s)", settings.position_mode, account_hedged)
    session = SessionRisk(settings)
    exit_tracker = ExitTracker() if settings.active_exit_enabled() else None
    if exit_tracker is not None:
        logger.info(
            "active exit enabled: stop_loss=%s%% take_profit=%s%% trailing=%s%% max_hold=%smin "
            "roe_tp=%s%% roe_sl=%s%% cg_oi_drop=%s%% cg_adverse_funding=%s",
            settings.exit_stop_loss_pct,
            settings.exit_take_profit_pct,
            settings.exit_trailing_pct,
            settings.exit_max_hold_minutes,
            settings.exit_take_profit_roe_pct,
            settings.exit_stop_loss_roe_pct,
            settings.exit_cg_oi_drop_pct,
            settings.exit_cg_adverse_funding,
        )
    boot_syms = candidate_pool.symbols() if candidate_pool is not None else None
    dashboard_state.set_boot_config(settings, candidate_symbols=boot_syms)
    dashboard_state.append_event("bot started")
    notify_bot_started(
        settings,
        symbols=boot_syms or [settings.symbol],
        strategy_label=_strategy_log_label(settings) if settings.signal_source == "strategy" else "llm",
    )
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
    else:
        try:
            eq, margin = fetch_futures_usdt_balance(ex)
            pool_syms = candidate_pool.symbols() if candidate_pool is not None else [settings.symbol]
            for sym in pool_syms:
                last_px = ex.fetch_ticker(sym).get("last") or ex.fetch_ticker(sym).get("close")
                sym_settings = settings.model_copy(update={"symbol": sym})
                warn_if_max_notional_below_minimum(
                    ex,
                    sym_settings,
                    last=float(last_px) if last_px else None,
                    equity_usdt=eq,
                    available_margin_usdt=margin,
                )
        except Exception as e:
            logger.debug("startup sizing check skipped: %s", e)

    logger.info(
        "markets loaded; signal_source=%s symbol_mode=%s symbols=%s testnet=%s dry_run=%s "
        "position_sizing=%s leverage=%s max_notional=%s min_confidence=%s once=%s hedged=%s "
        "openai_timeout=%ss exchange_timeout=%sms max_trades/day=%s max_daily_loss=%s warn_ratio=%s "
        "observability=%s:%s strategy=%s",
        settings.signal_source,
        settings.symbol_mode,
        ",".join(candidate_pool.symbols()) if candidate_pool is not None else settings.symbol,
        settings.binance_testnet,
        settings.dry_run,
        settings.position_sizing,
        settings.leverage,
        settings.max_notional_usdt,
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
            if candidate_pool is not None and candidate_pool.should_refresh():
                try:
                    candidate_pool.refresh(ex)
                    syms = candidate_pool.symbols()
                    dashboard_state.set_candidates(syms)
                    dashboard_state.append_event("candidate pool refreshed: " + ", ".join(syms))
                    notify_candidate_pool_refresh(settings, syms)
                    for sym in syms:
                        apply_symbol_leverage(ex, settings, symbol=sym)
                except Exception:
                    logger.exception("candidate pool refresh failed")
            if not once:
                _sleep_until_next_candle_close(settings.timeframe)
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
                    candidate_pool=candidate_pool,
                    exit_tracker=exit_tracker,
                    exit_coinglass=coinglass_client,
                )
            except Exception:
                logger.exception("tick failed")

            if cg_alert_watcher is not None and coinglass_client is not None:
                try:
                    pool_syms = candidate_pool.symbols() if candidate_pool is not None else [settings.symbol]
                    held_syms = list_held_symbols(ex, dry_run=settings.dry_run)
                    cg_alert_watcher.maybe_check(
                        settings,
                        coinglass_client,
                        candidate_symbols=pool_syms,
                        held_symbols=held_syms,
                    )
                except Exception:
                    logger.exception("coinglass alert check failed")

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
        __import__("binance_auto_ai.execution", fromlist=["build_exchange"])
        __import__("binance_auto_ai.positions", fromlist=["fetch_position_legs"])
        __import__("binance_auto_ai.llm_strategy", fromlist=["llm_decide"])
        __import__("binance_auto_ai.strategy_factory", fromlist=["build_live_strategy"])
        logger.info("smoke: imports OK")
        return

    settings = Settings()
    if settings.signal_source == "llm" and not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required when SIGNAL_SOURCE=llm")
    if not settings.dry_run and (not settings.binance_api_key or not settings.binance_api_secret):
        raise SystemExit("BINANCE_API_KEY/SECRET required when DRY_RUN=false")

    # 容器停止（SIGTERM）与 Ctrl-C（SIGINT）时优雅退出
    signal.signal(signal.SIGINT, _request_stop)
    try:
        signal.signal(signal.SIGTERM, _request_stop)
    except (AttributeError, ValueError):
        pass  # 部分平台/非主线程无法注册 SIGTERM

    try:
        run_loop(settings, once=args.once)
    except KeyboardInterrupt:
        logger.info("stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
