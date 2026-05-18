from __future__ import annotations

from pathlib import Path

import pytest


def test_state_file_redirects_to_app_state_in_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "app" / "state"
    state_dir.mkdir(parents=True)
    docker_state = state_dir / "state.json"

    monkeypatch.setenv("SYMBOL", "BTC/USDT:USDT")
    monkeypatch.setenv("STATE_FILE", ".futures_llm_bot_state.json")

    import futures_llm_bot.config as cfg

    monkeypatch.setattr(cfg, "_DOCKER_STATE_FILE", docker_state)
    monkeypatch.setattr(cfg, "_in_docker", lambda: True)

    from futures_llm_bot.config import Settings

    s = Settings()
    assert s.state_file == docker_state
