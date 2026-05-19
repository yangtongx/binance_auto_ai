from __future__ import annotations

from futures_llm_bot.dashboard_state import DashboardState
from futures_llm_bot.schemas import Action, LLMSignal


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
