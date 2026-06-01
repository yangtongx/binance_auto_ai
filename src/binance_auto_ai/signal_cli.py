"""命令行诊币：binance-auto-signal，分析单币信号不下单。"""

from __future__ import annotations

import argparse
import json
import sys

from binance_auto_ai.config import Settings
from binance_auto_ai.signal_probe import evaluate_symbol_signal
from binance_auto_ai.signal_timing_hints import _fmt_price


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="对指定 USDT 永续交易对做一次信号分析（不下单）。"
    )
    parser.add_argument(
        "--symbol",
        "-s",
        required=True,
        help="币种或交易对，如 DOGE、BTCUSDT、BTC/USDT:USDT",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON（默认为人可读摘要）",
    )
    args = parser.parse_args(argv)
    settings = Settings()
    result = evaluate_symbol_signal(settings, args.symbol)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif not result.ok:
        print(f"错误: {result.error}", file=sys.stderr)
        return 1
    else:
        print(
            f"{result.symbol} → {result.advice_cn} ({result.action}) "
            f"置信度 {result.confidence:.2f} · {result.source}/{result.strategy_label}"
        )
        print(f"原因: {result.reason}")
        if result.risk_message:
            print(f"风控: {result.risk_message}（当前配置下不会自动下单）")
        if result.timing_hints:
            print("--- 观望 · 时机参考（具体点位）---")
            for h in result.timing_hints:
                print(f"[{h.title}] 现价 {_fmt_price(h.current_price)}")
                for lv in h.levels:
                    print(f"  · {lv.line()}")
                if h.summary:
                    print(f"  {h.summary}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
