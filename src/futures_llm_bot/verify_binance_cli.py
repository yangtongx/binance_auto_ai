"""CLI: verify Binance USDM API keys (mainnet vs demo)."""

from __future__ import annotations

import sys

from futures_llm_bot.config import Settings
from futures_llm_bot.execution import build_exchange
from futures_llm_bot.exchange_env import load_binance_usdm_markets, resolve_binance_proxy


def main() -> None:
    s = Settings()
    print("BINANCE_TESTNET =", s.binance_testnet)
    print("proxy =", resolve_binance_proxy(s) or "(none)")
    print("key_len =", len(s.binance_api_key), "prefix =", repr(s.binance_api_key[:3]))
    print("secret_len =", len(s.binance_api_secret))
    if not s.binance_api_key or not s.binance_api_secret:
        print("Fill BINANCE_API_KEY / BINANCE_API_SECRET (or Docker secrets).", file=sys.stderr)
        raise SystemExit(1)
    ex = build_exchange(s)
    load_binance_usdm_markets(ex)
    print("enableDemoTrading =", ex.options.get("enableDemoTrading"))
    try:
        usdt = ex.fetch_balance().get("USDT")
        print("fetch_balance USDT:", usdt)
        print("OK")
    except Exception as e:
        print("FAILED:", e, file=sys.stderr)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
