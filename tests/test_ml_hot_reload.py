from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _inferable_module():
    m = MagicMock()
    m.eval = MagicMock()

    class _Y:
        def squeeze(self):
            return self

        def dim(self):
            return 1

        def detach(self):
            return self

        def float(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.array([0.1, 0.2, 0.7], dtype=np.float32)

    m.__call__ = MagicMock(return_value=_Y())
    return m


def test_ml_hot_reload_calls_jit_load_when_mtime_changes(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    from binance_auto_ai.ml_signal_strategy import TorchScriptMLStrategy

    p = tmp_path / "model.pt"
    p.write_bytes(b"dummy")

    first = _inferable_module()
    second = _inferable_module()
    load_round = {"i": 0}

    def jit_load_all(path: str, map_location: str | None = None):
        _ = path
        _ = map_location
        load_round["i"] += 1
        return first if load_round["i"] == 1 else second

    mt = {"ns": 100}

    def fake_stat(self: Path):
        m = MagicMock()
        m.st_mtime_ns = mt["ns"]
        return m

    with patch("torch.jit.load", side_effect=jit_load_all):
        with patch.object(Path, "stat", fake_stat):
            strat = TorchScriptMLStrategy(
                p,
                window=8,
                arch="mlp",
                size_pct=100.0,
                confidence=0.8,
                hot_reload=True,
                hot_reload_interval_sec=0.0,
            )

    ohlcv = [[i * 60_000, 1.0, 1.0, 1.0, 1.0 + i * 0.001, 1.0] for i in range(12)]

    def jit_load_reload_only(path: str, map_location: str | None = None):
        _ = path
        _ = map_location
        return _inferable_module()

    with patch("torch.jit.load", side_effect=jit_load_reload_only) as jl2:
        with patch.object(Path, "stat", fake_stat):
            strat.on_bar(11, ohlcv)
            assert jl2.call_count == 0
            mt["ns"] = 200
            strat.on_bar(11, ohlcv)
            assert jl2.call_count == 1
