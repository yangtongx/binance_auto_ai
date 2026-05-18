"""CLI: summarize Binance USDT-M income history (real exchange PnL, not backtest)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from futures_llm_bot.config import Settings
from futures_llm_bot.execution import build_exchange
from futures_llm_bot.real_pnl import (
    aggregate_income_by_type,
    dt_to_ms,
    fetch_um_income_rows,
    parse_iso_date_utc,
    trading_cashflow_usdt,
    um_income_native_symbol,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize Binance USDT-M futures income (REALIZED_PNL, FUNDING_FEE, COMMISSION, …) from /fapi/v1/income.",
    )
    parser.add_argument(
        "--days",
        type=float,
        default=None,
        help="If set, load income from now-days (UTC) through now. Ignored if --since is set.",
    )
    parser.add_argument("--since", type=str, default=None, help="UTC start date/datetime, e.g. 2026-01-01 or 2026-01-01T00:00:00Z")
    parser.add_argument("--until", type=str, default=None, help="UTC end date/datetime (default: now UTC)")
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Linear perpetual symbol (default: SYMBOL from .env). Use with --all-contracts for whole account.",
    )
    parser.add_argument(
        "--all-contracts",
        action="store_true",
        help="Do not filter by symbol (entire USDT-M wallet income in range).",
    )
    args = parser.parse_args()

    settings = Settings()
    if not settings.binance_api_key or not settings.binance_api_secret:
        raise SystemExit("BINANCE_API_KEY and BINANCE_API_SECRET are required")

    now = datetime.now(timezone.utc)
    if args.since:
        start = parse_iso_date_utc(args.since)
    elif args.days is not None:
        if args.days <= 0:
            raise SystemExit("--days must be positive")
        start = now - timedelta(days=args.days)
    else:
        raise SystemExit("Provide --days or --since")

    if args.until:
        end = parse_iso_date_utc(args.until)
    else:
        end = now

    start_ms = dt_to_ms(start)
    end_ms = dt_to_ms(end)
    if start_ms >= end_ms:
        raise SystemExit("start must be before until/now")

    unified = (args.symbol if args.symbol is not None else settings.symbol).strip()
    from futures_llm_bot.exchange_env import load_binance_usdm_markets

    ex = build_exchange(settings)
    load_binance_usdm_markets(ex)
    sym_native: str | None = None
    label: str
    if args.all_contracts or not unified:
        sym_native = None
        label = "(all USDT-M contracts)"
    else:
        sym_native = um_income_native_symbol(ex, unified)
        label = unified

    rows = fetch_um_income_rows(ex, start_ms=start_ms, end_ms=end_ms, symbol_native=sym_native)
    by_type = aggregate_income_by_type(rows)
    trade_flow = trading_cashflow_usdt(by_type)

    print(f"rows={len(rows)} start_utc={start.isoformat()} end_utc={end.isoformat()} symbol_filter={label}")
    print("--- by incomeType (USDT, signed) ---")
    for k, v in by_type.items():
        print(f"  {k:24} {v:+.8f}")
    print("--- trading cashflow (REALIZED_PNL + FUNDING_FEE + COMMISSION + INSURANCE_CLEAR) ---")
    print(f"  {trade_flow:+.8f} USDT")
    print(
        "\nNote: excludes TRANSFER and other non-trade lines; open positions still have unrealized PnL in the account snapshot.",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("stopped")
        sys.exit(130)
