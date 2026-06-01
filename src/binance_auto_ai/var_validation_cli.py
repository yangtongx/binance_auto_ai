#!/usr/bin/env python3
"""命令行：binance-auto-var-validate，历史收益 VaR 违约率与 Kupiec 检验。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Historical VaR backtest: rolling quantile violations + Kupiec LR (coverage).",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=Path, help="OHLCV CSV (timestamp_ms,o,h,l,c,v)")
    src.add_argument("--fetch", action="store_true", help="Download via CCXT Binance USDM")
    p.add_argument("--symbol", default="BTC/USDT:USDT")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--no-testnet", action="store_true")
    p.add_argument("--page-size", type=int, default=1500)
    p.add_argument("--max-requests", type=int, default=500)
    p.add_argument("--lookback", type=int, default=250, help="Rolling window for VaR estimate")
    p.add_argument("--alpha", type=float, default=0.05, help="Target left-tail mass (e.g. 0.05)")
    p.add_argument("--json-out", type=Path)
    args = p.parse_args()

    root = Path(__file__).resolve().parents[2]
    src_dir = str(root / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    from binance_auto_ai.backtest.data import fetch_ohlcv_ccxt_paginated, load_ohlcv_csv
    from binance_auto_ai.risk_metrics import log_returns_from_closes
    from binance_auto_ai.var_validation import var_backtest_report

    if args.fetch:
        ohlcv = fetch_ohlcv_ccxt_paginated(
            symbol=args.symbol,
            timeframe=args.timeframe,
            max_bars=args.limit,
            testnet=not args.no_testnet,
            page_size=args.page_size,
            max_requests=args.max_requests,
        )
        logger.info("loaded %s bars %s %s", len(ohlcv), args.symbol, args.timeframe)
    else:
        ohlcv = load_ohlcv_csv(args.csv)

    closes = np.asarray([float(r[4]) for r in ohlcv], dtype=np.float64)
    rets = log_returns_from_closes(closes)
    if rets.size <= args.lookback + 10:
        raise SystemExit(f"need more returns (got {rets.size}, lookback={args.lookback})")

    rep = var_backtest_report(rets, lookback=args.lookback, alpha=args.alpha)
    print(json.dumps(rep, indent=2, default=str))
    if args.json_out:
        args.json_out.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    logger.info(
        "VaR backtest n=%s violations=%s rate=%.4f alpha=%s LR=%.3f reject_5pct=%s",
        rep["n_forecasts"],
        rep["violations"],
        rep["violation_rate"],
        args.alpha,
        rep["kupiec_lr"],
        rep["reject_h0_coverage_5pct"],
    )


if __name__ == "__main__":
    main()
