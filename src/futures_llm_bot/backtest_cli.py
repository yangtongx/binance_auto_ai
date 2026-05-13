"""CLI: run rule-based backtest on CCXT history or CSV."""

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

_STRATEGIES = ("sma_cross", "rsi", "macd", "bollinger", "bb")


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
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--max-notional", type=float, default=1_000.0)
    p.add_argument("--fee-bps", type=float, default=4.0)
    p.add_argument("--json-out", type=Path, help="Write summary JSON")
    args = p.parse_args()

    need = min_bars_for_backtest(
        args.strategy,
        slow=args.slow,
        rsi_period=args.rsi_period,
        macd_signal=args.macd_signal,
        bb_period=args.bb_period,
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
