from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_docker_secret_file_overrides_empty_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key_file = tmp_path / "binance_key"
    key_file.write_text("test-api-key\n", encoding="utf-8")
    monkeypatch.setenv("BINANCE_API_KEY", "")
    monkeypatch.setenv("BINANCE_API_KEY_FILE", str(key_file))

    from binance_auto_ai.config import _load_docker_secrets

    _load_docker_secrets()
    assert os.environ["BINANCE_API_KEY"] == "test-api-key"
