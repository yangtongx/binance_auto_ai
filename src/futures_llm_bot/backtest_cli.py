"""命令行回测：futures-llm-backtest，用历史 K 线跑规则策略并输出收益统计。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from futures_llm_bot.backtest.data import fetch_ohlcv_ccxt, load_ohlcv_csv
from futures_llm_bot.backtest.engine import run_backtest
from futures_llm_bot.strategy_factory import build_strategy_for_backtest, min_bars_for_backtest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_STRATEGIES = (
    "sma_cross",
    "rsi",
    "rsi_adaptive",
    "macd",
    "bollinger",
    "bb",
    "ichimoku",
    "ichi",
    "fibonacci",
    "fib",
    "volume_profile",
    "vp",
    "stochastic",
    "stoch",
    "atr_breakout",
    "atr",
    "ml",
    "composite",
    "rl_sb3",
)


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest a deterministic strategy (route 1: rules + history).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=Path, help="OHLCV CSV (timestamp_ms,o,h,l,c,v)")
    src.add_argument("--fetch", action="store_true", help="Download via CCXT (Binance USDM testnet)")
    p.add_argument("--symbol", default="BTC/USDT:USDT", help="With --fetch")
    p.add_argument("--timeframe", default="1h", help="With --fetch")
    p.add_argument("--limit", type=int, default=500, help="Bars with --fetch")
    p.add_argument("--no-testnet", action="store_true", help="With --fetch: use mainnet public data")
    p.add_argument("--strategy", default="sma_cross", choices=_STRATEGIES, help="Rule strategy id (matches STRATEGY_NAME live)")
    p.add_argument("--fast", type=int, default=10, help="SMA fast or MACD fast EMA span")
    p.add_argument("--slow", type=int, default=30, help="SMA slow or MACD slow EMA span")
    p.add_argument("--rsi-period", type=int, default=14)
    p.add_argument("--rsi-oversold", type=float, default=30.0)
    p.add_argument("--rsi-overbought", type=float, default=70.0)
    p.add_argument("--macd-signal", type=int, default=9)
    p.add_argument("--bb-period", type=int, default=20)
    p.add_argument("--bb-std", type=float, default=2.0)
    p.add_argument("--ichi-tenkan", type=int, default=9)
    p.add_argument("--ichi-kijun", type=int, default=26)
    p.add_argument("--ichi-senkou-b", type=int, default=52)
    p.add_argument("--fib-lookback", type=int, default=50)
    p.add_argument("--fib-level", default="0.618", choices=("0.382", "0.5", "0.618"))
    p.add_argument("--vp-bars", type=int, default=48)
    p.add_argument("--vp-bins", type=int, default=24)
    p.add_argument("--ml-backend", default="torch", help="torch|tensorflow (with STRATEGY=ml)")
    p.add_argument("--ml-model", type=Path, help="Model path (required for --strategy ml)")
    p.add_argument("--ml-window", type=int, default=32)
    p.add_argument("--ml-torch-arch", default="mlp", choices=("mlp", "lstm", "transformer"))
    p.add_argument("--stoch-k", type=int, default=14)
    p.add_argument("--stoch-d", type=int, default=3)
    p.add_argument("--stoch-oversold", type=float, default=20.0)
    p.add_argument("--stoch-overbought", type=float, default=80.0)
    p.add_argument("--atr-period", type=int, default=14)
    p.add_argument("--atr-mult", type=float, default=1.5)
    p.add_argument(
        "--composite-members",
        default="",
        help="For --strategy composite: comma-separated strategy ids (e.g. rsi,macd)",
    )
    p.add_argument(
        "--composite-mode",
        default="majority",
        choices=("majority", "weighted", "unanimous", "first"),
    )
    p.add_argument(
        "--composite-weights",
        default="",
        help="Optional comma weights for composite weighted mode (one per member)",
    )
    p.add_argument("--vol-window", type=int, default=20, help="rsi_adaptive rolling vol length")
    p.add_argument("--vol-ref-window", type=int, default=100, help="rsi_adaptive vol reference median window")
    p.add_argument("--vol-sensitivity", type=float, default=10.0, help="rsi_adaptive RSI threshold shift scale")
    p.add_argument("--rl-model", type=Path, help="Stable-Baselines3 zip for --strategy rl_sb3")
    p.add_argument("--rl-window", type=int, default=32)
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--max-notional", type=float, default=1_000.0)
    p.add_argument("--fee-bps", type=float, default=4.0)
    p.add_argument("--json-out", type=Path, help="Write summary JSON")
    args = p.parse_args()

    if args.strategy == "composite" and not args.composite_members.strip():
        raise SystemExit("--composite-members is required when --strategy composite")
    if args.strategy == "rl_sb3" and not args.rl_model:
        raise SystemExit("--rl-model is required when --strategy rl_sb3")

    need = min_bars_for_backtest(
        args.strategy,
        slow=args.slow,
        rsi_period=args.rsi_period,
        macd_signal=args.macd_signal,
        bb_period=args.bb_period,
        senkou_b=args.ichi_senkou_b,
        fib_lookback=args.fib_lookback,
        vp_bars=args.vp_bars,
        ml_window=args.ml_window,
        stoch_k=args.stoch_k,
        stoch_d=args.stoch_d,
        atr_period=args.atr_period,
        vol_window=args.vol_window,
        vol_ref_window=args.vol_ref_window,
        rl_window=args.rl_window,
        composite_members=args.composite_members,
    )

    if args.fetch:
        ohlcv = fetch_ohlcv_ccxt(
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            testnet=not args.no_testnet,
        )
    else:
        ohlcv = load_ohlcv_csv(args.csv)

    if len(ohlcv) < need:
        raise SystemExit(f"need more bars (got {len(ohlcv)}, need>={need} for strategy={args.strategy})")

    if args.strategy == "ml":
        if not args.ml_model:
            raise SystemExit("--ml-model is required when --strategy ml")
    strat = build_strategy_for_backtest(
        args.strategy,
        fast=args.fast,
        slow=args.slow,
        rsi_period=args.rsi_period,
        rsi_oversold=args.rsi_oversold,
        rsi_overbought=args.rsi_overbought,
        macd_signal=args.macd_signal,
        bb_period=args.bb_period,
        bb_std=args.bb_std,
        ichimoku_tenkan=args.ichi_tenkan,
        ichimoku_kijun=args.ichi_kijun,
        ichimoku_senkou_b=args.ichi_senkou_b,
        fib_lookback=args.fib_lookback,
        fib_level=args.fib_level,
        vp_bars=args.vp_bars,
        vp_bins=args.vp_bins,
        ml_backend=args.ml_backend,
        ml_model_path=args.ml_model or "",
        ml_window=args.ml_window,
        ml_torch_arch=args.ml_torch_arch,
        stoch_k=args.stoch_k,
        stoch_d=args.stoch_d,
        stoch_oversold=args.stoch_oversold,
        stoch_overbought=args.stoch_overbought,
        atr_period=args.atr_period,
        atr_mult=args.atr_mult,
        composite_members=args.composite_members,
        composite_mode=args.composite_mode,
        composite_weights=args.composite_weights,
        vol_window=args.vol_window,
        vol_ref_window=args.vol_ref_window,
        vol_sensitivity=args.vol_sensitivity,
        rl_model_path=str(args.rl_model) if args.rl_model else "",
        rl_window=args.rl_window,
    )
    res = run_backtest(
        ohlcv,
        strat,
        initial_cash_usdt=args.cash,
        max_notional_usdt=args.max_notional,
        fee_bps=args.fee_bps,
    )

    summary = {
        "strategy": args.strategy,
        "bars": len(ohlcv),
        "trades": len(res.trades),
        "total_return_pct": round(res.total_return_pct, 4),
        "max_drawdown_pct": round(res.max_drawdown_pct, 4),
        "final_equity_usdt": round(res.equity_curve[-1], 4) if res.equity_curve else None,
    }
    print(json.dumps(summary, indent=2))
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logger.info("backtest done trades=%s return=%.2f%% max_dd=%.2f%%", len(res.trades), res.total_return_pct, res.max_drawdown_pct)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
