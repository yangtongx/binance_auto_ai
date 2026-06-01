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
