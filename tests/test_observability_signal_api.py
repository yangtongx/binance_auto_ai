from __future__ import annotations

import json
import socket
import time
from unittest.mock import patch
from urllib.request import urlopen

from binance_auto_ai.observability import start_observability_background
from binance_auto_ai.signal_probe import SignalProbeResult


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_api_signal_endpoint() -> None:
    port = _free_port()
    fake = SignalProbeResult(
        ok=True,
        symbol_input="DOGE",
        symbol="DOGE/USDT:USDT",
        action="hold",
        action_cn="观望",
        advice="watch",
        advice_cn="观望",
        confidence=0.5,
        reason="test",
        source="strategy",
    )

    with (
        patch("binance_auto_ai.observability.Settings") as st_cls,
        patch("binance_auto_ai.observability.evaluate_symbol_signal", return_value=fake) as ev,
    ):
        st_cls.return_value = object()
        start_observability_background("127.0.0.1", port)
        time.sleep(0.25)
        url = f"http://127.0.0.1:{port}/api/signal?symbol=DOGE"
        with urlopen(url, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        ev.assert_called_once()

    assert body["ok"] is True
    assert body["symbol"] == "DOGE/USDT:USDT"
    assert body["advice_cn"] == "观望"
