"""交易所真实盈亏：调用币安 /fapi/v1/income 汇总（非回测模拟）。"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import ccxt

logger = logging.getLogger(__name__)

# 核心流水类型，合起来解释交易带来的钱包变动（不含划转/赠金等）
_TRADING_INCOME_TYPES = frozenset(
    {
        "REALIZED_PNL",
        "FUNDING_FEE",
        "COMMISSION",
        "INSURANCE_CLEAR",
    }
)


def parse_iso_date_utc(s: str) -> datetime:
    """Parse ``YYYY-MM-DD`` or ISO datetime; assume UTC if no tz."""
    s = s.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dt_to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def um_income_native_symbol(ex: ccxt.binanceusdm, unified_symbol: str) -> str:
    ex.load_markets()
    return str(ex.market(unified_symbol)["id"])


def fetch_um_income_rows(
    ex: ccxt.binanceusdm,
    *,
    start_ms: int,
    end_ms: int | None,
    symbol_native: str | None = None,
) -> list[dict[str, Any]]:
    """Paginate Binance USDM income history (raw rows). Requires API keys + ``load_markets`` ok."""
    out: list[dict[str, Any]] = []
    cursor = start_ms
    while True:
        req: dict[str, Any] = {"startTime": cursor, "limit": 1000}
        if end_ms is not None:
            req["endTime"] = end_ms
        if symbol_native:
            req["symbol"] = symbol_native
        batch = ex.fapiPrivateGetIncome(req)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1000:
            break
        last_t = max(int(x["time"]) for x in batch)
        next_c = last_t + 1
        if next_c <= cursor:
            logger.warning("income pagination stalled at time=%s; stopping", last_t)
            break
        cursor = next_c
        if end_ms is not None and cursor > end_ms:
            break
    return out


def aggregate_income_by_type(rows: list[dict[str, Any]]) -> dict[str, float]:
    by_type: dict[str, float] = defaultdict(float)
    for r in rows:
        it = str(r.get("incomeType") or "")
        try:
            amt = float(r.get("income") or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        by_type[it] += amt
    return dict(sorted(by_type.items(), key=lambda kv: kv[0]))


def trading_cashflow_usdt(by_type: dict[str, float]) -> float:
    """Sum of realized PnL, funding, commission, insurance clear (signed, as Binance reports)."""
    return sum(by_type.get(k, 0.0) for k in _TRADING_INCOME_TYPES)
