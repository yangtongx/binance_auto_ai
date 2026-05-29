#!/usr/bin/env python3
"""裁剪 Docker json-file 日志，仅保留最近 N 小时（按每行 JSON 的 time 字段）。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_docker_log_time(raw: str) -> datetime:
    s = str(raw).strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def filter_log_file(src: Path, dst: Path, *, keep_hours: float) -> tuple[int, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=keep_hours)
    if not src.is_file():
        dst.write_text("", encoding="utf-8")
        return 0, 0

    kept: list[str] = []
    total = 0
    for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        total += 1
        try:
            obj = json.loads(line)
            ts = obj.get("time")
            if not ts:
                continue
            if parse_docker_log_time(ts) >= cutoff:
                kept.append(line)
        except (json.JSONDecodeError, TypeError, ValueError):
            # 无法解析时间戳的行丢弃，避免把旧格式脏数据一直留着
            continue

    text = "\n".join(kept)
    if text:
        text += "\n"
    dst.write_text(text, encoding="utf-8")
    return total, len(kept)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Trim Docker json-file logs to the last N hours.")
    p.add_argument("log_path", type=Path, help="Path from docker inspect .LogPath")
    p.add_argument("output", type=Path, help="Filtered output file")
    p.add_argument("--hours", type=float, default=2.0, help="Keep this many hours (default 2)")
    args = p.parse_args(argv)

    total, kept = filter_log_file(args.log_path, args.output, keep_hours=args.hours)
    print(f"lines: {total} -> {kept} (keep last {args.hours}h, cutoff UTC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
