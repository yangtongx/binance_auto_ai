"""Display timestamps in China Standard Time (UTC+8 / Asia/Shanghai)."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
DISPLAY_TZ_LABEL = "北京时间"


def utc_now_iso() -> str:
    """UTC ISO timestamp for storage and APIs."""
    return datetime.now(timezone.utc).isoformat()


def format_iso_to_display(iso: str, *, compact: bool = False) -> str:
    """Convert a UTC (or offset-aware) ISO string to Asia/Shanghai for UI/logs."""
    if not iso or not str(iso).strip():
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(iso)[:19]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(DISPLAY_TZ)
    if compact:
        return local.strftime("%m-%d %H:%M:%S")
    return local.strftime("%Y-%m-%d %H:%M:%S")
