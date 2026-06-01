from __future__ import annotations

import pytest

from binance_auto_ai.config import Settings
from binance_auto_ai.execution import verify_position_mode_alignment


class _Ex:
    def __init__(self, hedged: bool) -> None:
        self._hedged = hedged

    def fetchPositionMode(self) -> dict:
        return {"hedged": self._hedged}


def test_verify_rejects_oneway_when_account_hedged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSITION_MODE", "oneway")
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    settings = Settings()
    with pytest.raises(SystemExit, match="-4061"):
        verify_position_mode_alignment(_Ex(hedged=True), settings)
