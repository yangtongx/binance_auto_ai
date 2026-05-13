from __future__ import annotations

import pytest

from futures_llm_bot.real_pnl import aggregate_income_by_type, parse_iso_date_utc, trading_cashflow_usdt


def test_parse_iso_date_utc_date_only() -> None:
    d = parse_iso_date_utc("2026-03-15")
    assert d.tzinfo is not None
    assert d.year == 2026 and d.month == 3 and d.day == 15


def test_aggregate_and_trading_cashflow_excludes_transfer() -> None:
    rows = [
        {"incomeType": "REALIZED_PNL", "income": "1.5"},
        {"incomeType": "REALIZED_PNL", "income": "-0.25"},
        {"incomeType": "FUNDING_FEE", "income": "-0.10"},
        {"incomeType": "COMMISSION", "income": "-0.05"},
        {"incomeType": "TRANSFER", "income": "100"},
    ]
    by_t = aggregate_income_by_type(rows)
    assert by_t["REALIZED_PNL"] == 1.25
    assert by_t["TRANSFER"] == 100.0
    assert trading_cashflow_usdt(by_t) == pytest.approx(1.25 - 0.10 - 0.05)
