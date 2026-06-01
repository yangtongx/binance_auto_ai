"""命令行：验证币安 USDT-M API 密钥与连通性（主网/演示盘）。"""

from __future__ import annotations

import sys

from binance_auto_ai.config import Settings
from binance_auto_ai.execution import build_exchange
from binance_auto_ai.exchange_env import load_binance_usdm_markets, resolve_binance_proxy


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
