from __future__ import annotations

from pathlib import Path

from binance_auto_ai.schemas import Action
from binance_auto_ai.session_risk import SessionRisk


def test_session_risk_trade_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "risk_state.json"))
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MAX_TRADES_PER_DAY", "1")
    monkeypatch.setenv("MAX_DAILY_LOSS_USDT", "0")
    from binance_auto_ai.config import Settings

    s = Settings()
    r = SessionRisk(s)
    assert r.block_reason_for(Action.LONG, current_equity=1000.0) is None
    r.record_executed_order()
    assert r.block_reason_for(Action.SHORT, current_equity=1000.0) is not None
    assert r.block_reason_for(Action.FLAT, current_equity=1000.0) is None


def test_session_risk_loss_requires_equity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "risk_state2.json"))
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MAX_TRADES_PER_DAY", "0")
    monkeypatch.setenv("MAX_DAILY_LOSS_USDT", "10")
    from binance_auto_ai.config import Settings

    s = Settings()
    r = SessionRisk(s)
    assert "equity" in (r.block_reason_for(Action.LONG, current_equity=None) or "").lower()


def test_session_risk_skipped_on_testnet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "risk_testnet.json"))
    monkeypatch.setenv("MAX_TRADES_PER_DAY", "1")
    monkeypatch.setenv("MAX_DAILY_LOSS_USDT", "10")
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    from binance_auto_ai.config import Settings

    s = Settings()
    r = SessionRisk(s)
    r.record_executed_order()
    assert r.block_reason_for(Action.LONG, current_equity=0.0) is None
