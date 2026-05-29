from __future__ import annotations

import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _filter_log_file(src: Path, dst: Path, *, keep_hours: float):
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "trim_docker_logs.py"
    spec = importlib.util.spec_from_file_location("trim_docker_logs", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.filter_log_file(src, dst, keep_hours=keep_hours)


def test_filter_keeps_recent_lines() -> None:
    now = datetime.now(timezone.utc)
    old = (now.replace(microsecond=0)).isoformat().replace("+00:00", "Z")
    recent_ts = now.isoformat().replace("+00:00", "Z")
    lines = [
        json.dumps({"log": "old\n", "stream": "stdout", "time": "2020-01-01T00:00:00.000000000Z"}),
        json.dumps({"log": "new\n", "stream": "stdout", "time": recent_ts}),
    ]
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "a.log"
        dst = Path(td) / "b.log"
        src.write_text("\n".join(lines) + "\n", encoding="utf-8")
        total, kept = _filter_log_file(src, dst, keep_hours=2.0)
        assert total == 2
        assert kept == 1
        out = dst.read_text(encoding="utf-8")
        assert "new" in out
        assert "old" not in out
