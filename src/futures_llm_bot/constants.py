"""Tolerances for CCXT / exchange float noise (not exchange min lot sizes)."""

# One-way net position treated as flat (|signed contracts| below this).
NET_POSITION_EPS_CONTRACTS = 1e-12

# Per-leg contracts treated as flat after reduce-only + poll (slightly looser than net).
LEG_POSITION_EPS_CONTRACTS = 1e-9

# Reject mark/last outside this range as non-finite or corrupt ticker data.
MIN_SANE_MARK_USDT = 1e-12
MAX_SANE_MARK_USDT = 1e12
