from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from binance_auto_ai.dashboard_state import DashboardState
from binance_auto_ai.schemas import Action, LLMSignal


def test_dashboard_snapshot_roundtrip() -> None:
    st = DashboardState()
    sig = LLMSignal(action=Action.LONG, size_pct=10.0, confidence=0.8, reason="test")
    st.set_boot_config(
        type("S", (), {
            "symbol": "BTC/USDT:USDT",
            "symbol_mode": "single",
            "signal_source": "strategy",
            "strategy_name": "sma_cross",
            "timeframe": "1m",
            "dry_run": True,
            "binance_testnet": True,
            "position_sizing": "fixed",
            "leverage": 10,
            "max_notional_usdt": 100.0,
            "min_confidence": 0.5,
            "symbol_candidates": "auto",
        })(),
        candidate_symbols=["DOGE/USDT:USDT", "SOL/USDT:USDT"],
    )
    st.set_signals({"DOGE/USDT:USDT": sig})
    st.append_decision(symbol="DOGE/USDT:USDT", signal=sig, source="strategy", outcome="dry_run")
    snap = st.snapshot()
    assert snap["config"]["symbol_mode"] == "single"
    assert "DOGE/USDT:USDT" in snap["signals"]
    assert snap["decisions"][0]["outcome"] == "dry_run"


def _seed_equity(st: DashboardState, points: list[tuple[datetime, float]]) -> None:
    for ts, v in points:
        st._equity_history.append({"t": ts.isoformat(), "v": v})


def test_equity_range_filters_and_downsamples() -> None:
    st = DashboardState()
    now = datetime.now(timezone.utc)
    pts = [(now - timedelta(minutes=i), 100.0 + i) for i in range(120, 0, -1)]
    _seed_equity(st, pts)

    last_hour = st.equity_range("1h", max_points=200)
    assert last_hour["range"] == "1h"
    # 1h 窗口应包含 120 点中约 60 个
    assert 55 <= last_hour["raw_count"] <= 61
    assert len(last_hour["points"]) <= 200

    all_range = st.equity_range("all", max_points=50)
    assert all_range["raw_count"] == 120
    assert len(all_range["points"]) <= 50
    # 降采样后仍保留最后一点
    assert all_range["points"][-1]["v"] == pts[-1][1]


def test_equity_persist_and_load(tmp_path: Path) -> None:
    path = tmp_path / "equity_history.json"
    st = DashboardState(persist_path=path)
    now = datetime.now(timezone.utc)
    st._equity_history.append({"t": now.isoformat(), "v": 42.5})
    # 绕过节流强制持久化
    st._last_persist_monotonic = 0.0
    st._persist_throttled()
    assert path.is_file()

    st2 = DashboardState(persist_path=path)
    history = list(st2._equity_history)
    assert len(history) == 1
    assert history[0]["v"] == 42.5
