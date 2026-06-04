"""Config validation for SYMBOL_MODE=signal_pick."""

from __future__ import annotations

import pytest

from binance_auto_ai.config import Settings


def test_signal_pick_requires_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYMBOL_MODE", "signal_pick")
    monkeypatch.setenv("SYMBOL_CANDIDATES", "DOGE/USDT:USDT")
    monkeypatch.setenv("SIGNAL_SOURCE", "strategy")
    with pytest.raises(ValueError, match="at least 2"):
        Settings()


def test_signal_pick_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYMBOL_MODE", "signal_pick")
    monkeypatch.setenv("SYMBOL_CANDIDATES", "DOGE/USDT:USDT,SOL/USDT:USDT")
    monkeypatch.setenv("SIGNAL_SOURCE", "strategy")
    s = Settings()
    assert s.candidate_symbols() == ["DOGE/USDT:USDT", "SOL/USDT:USDT"]


def test_signal_pick_auto_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYMBOL_MODE", "signal_pick")
    monkeypatch.setenv("SYMBOL_CANDIDATES", "auto")
    monkeypatch.setenv("SIGNAL_SOURCE", "strategy")
    s = Settings()
    assert s.symbol_candidates_is_auto() is True


def test_rank_weights_mismatch_falls_back_to_equal(monkeypatch: pytest.MonkeyPatch) -> None:
    """RANK_BY 与 WEIGHTS 数量不一致时不应崩溃（常见于只更新了其中一行 .env）。"""
    monkeypatch.setenv("SYMBOL_MODE", "signal_pick")
    monkeypatch.setenv("SYMBOL_CANDIDATES", "auto")
    monkeypatch.setenv("SIGNAL_SOURCE", "strategy")
    monkeypatch.setenv("SYMBOL_CANDIDATES_RANK_BY", "momentum,cg_oi_change,liquidity")
    monkeypatch.setenv("SYMBOL_CANDIDATES_RANK_WEIGHTS", "0.12,0.18,0.14,0.14,0.12,0.10,0.10")
    s = Settings()
    assert s.candidate_rank_metrics() == ["momentum", "cg_oi_change", "quote_volume"]
    w = s.candidate_rank_weights()
    assert len(w) == 3
    assert abs(sum(w) - 1.0) < 1e-6
