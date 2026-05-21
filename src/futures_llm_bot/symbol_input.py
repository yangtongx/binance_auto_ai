"""Resolve user-typed symbols to CCXT USDT-M linear perpetual ids."""

from __future__ import annotations

import re

import ccxt

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:[A-Za-z0-9._-]+$")


def candidate_ccxt_symbols(raw: str) -> list[str]:
    """Build likely CCXT symbol strings from free-form user input."""
    s = str(raw or "").strip()
    if not s:
        return []
    if _SYMBOL_RE.match(s):
        return [s]
    if "/" in s:
        base = s if ":" in s else f"{s}:USDT"
        return [base]
    upper = s.upper().replace(" ", "")
    if upper.endswith("USDT") and len(upper) > 4:
        base = upper[:-4]
        return [f"{base}/USDT:USDT"]
    return [f"{upper}/USDT:USDT"]


def resolve_usdm_symbol(ex: ccxt.binanceusdm, raw: str) -> str:
    """Map user input to an active USDT-M perpetual symbol on the loaded exchange."""
    candidates = candidate_ccxt_symbols(raw)
    if not candidates:
        raise ValueError("请输入交易对，例如 DOGE、DOGEUSDT 或 DOGE/USDT:USDT")

    markets = ex.markets or {}
    for sym in candidates:
        m = markets.get(sym)
        if m and m.get("active", True) and m.get("linear"):
            return sym

    # Fallback: match CCXT market id (e.g. DOGEUSDT) case-insensitively.
    want = candidates[-1].split("/")[0].split(":")[0].upper()
    for sym, m in markets.items():
        if not m.get("active", True) or not m.get("linear"):
            continue
        mid = str(m.get("id") or "").upper()
        base = str(m.get("base") or "").upper()
        if mid == f"{want}USDT" or base == want:
            return sym

    hint = "、".join(candidates)
    raise ValueError(f"未找到 USDT 永续合约：{raw!r}（尝试过 {hint}）")
