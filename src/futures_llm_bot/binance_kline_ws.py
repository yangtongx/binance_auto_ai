"""币安 USDT-M K 线 WebSocket 缓冲：REST 预热 + 收盘推送，供 USE_WEBSOCKET=true 时策略用。"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


def _ws_url(*, testnet: bool, stream_path: str) -> str:
    from futures_llm_bot.exchange_env import binance_usdm_ws_base

    base = binance_usdm_ws_base(testnet=testnet)
    return f"{base}/{stream_path}"


def reconnect_delay_sec(
    attempt: int,
    *,
    base_sec: float,
    max_sec: float,
    jitter_frac: float,
) -> float:
    """Exponential backoff with symmetric jitter (attempt is 1-based after a disconnect)."""
    if attempt < 1:
        return 0.0
    raw = min(max_sec, base_sec * (2 ** min(attempt - 1, 10)))
    if jitter_frac <= 0:
        return float(raw)
    j = jitter_frac * float(raw)
    return max(base_sec * 0.1, raw + random.uniform(-j, j))


class BinanceUsdMKlineBuffer:
    """Thread-safe deque of OHLCV rows ``[ts_ms,o,h,l,c,v]`` (CCXT shape)."""

    def __init__(
        self,
        exchange: Any,
        *,
        symbol: str,
        timeframe: str,
        testnet: bool,
        max_len: int = 1500,
        reconnect_base_sec: float = 1.0,
        reconnect_max_sec: float = 60.0,
        reconnect_jitter: float = 0.25,
    ) -> None:
        self._ex = exchange
        self._symbol = symbol
        self._tf = timeframe.strip()
        self._testnet = testnet
        self._max_len = max_len
        self._reconnect_base = reconnect_base_sec
        self._reconnect_max = reconnect_max_sec
        self._reconnect_jitter = reconnect_jitter
        self._dq: deque[list[float]] = deque(maxlen=max_len)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        m = exchange.market(symbol)
        self._stream_sym: str = str(m.get("id", "")).lower()
        if not self._stream_sym:
            raise ValueError(f"cannot resolve Binance stream id for {symbol}")

    def seed_from_rest(self, *, limit: int) -> None:
        rows = self._ex.fetch_ohlcv(self._symbol, timeframe=self._tf, limit=limit)
        with self._lock:
            self._dq.clear()
            for r in rows:
                self._dq.append([float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])

    def get_snapshot(self, limit: int) -> list[list[float]]:
        with self._lock:
            out = list(self._dq)[-limit:]
        return out

    def start(self) -> None:
        try:
            import websocket  # type: ignore
        except ImportError as e:
            raise RuntimeError('WebSocket support requires: pip install -e ".[realtime]"') from e

        stream = f"{self._stream_sym}@kline_{self._tf}"
        url = _ws_url(testnet=self._testnet, stream_path=stream)

        failures = 0
        lock = threading.Lock()

        def on_message(_ws: Any, message: str) -> None:
            try:
                self._handle_message(message)
            except Exception:
                logger.exception("ws kline handler error")

        def on_error(_ws: Any, error: Exception) -> None:
            logger.warning("websocket error: %s", error)

        def on_close(_ws: Any, _code: int | None = None, _msg: str | None = None) -> None:
            logger.info("websocket closed; will reconnect if still running")

        def on_open(_ws: Any) -> None:
            nonlocal failures
            with lock:
                failures = 0
            logger.info("websocket connected stream=%s tf=%s", self._stream_sym, self._tf)

        def run() -> None:
            nonlocal failures
            while not self._stop.is_set():
                try:
                    ws = websocket.WebSocketApp(
                        url,
                        on_message=on_message,
                        on_error=on_error,
                        on_close=on_close,
                        on_open=on_open,
                    )
                    ws.run_forever(ping_interval=20, ping_timeout=10)
                except Exception:
                    logger.exception("websocket run_forever failed")
                if self._stop.is_set():
                    break
                with lock:
                    failures += 1
                    att = failures
                delay = reconnect_delay_sec(
                    att,
                    base_sec=self._reconnect_base,
                    max_sec=self._reconnect_max,
                    jitter_frac=self._reconnect_jitter,
                )
                logger.warning(
                    "websocket reconnect in %.1fs (failure #%s, max=%.1fs base=%.1fs)",
                    delay,
                    att,
                    self._reconnect_max,
                    self._reconnect_base,
                )
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline:
                    if self._stop.wait(0.2):
                        break

        self._stop.clear()
        self._thread = threading.Thread(target=run, name="binance-kline-ws", daemon=True)
        self._thread.start()
        logger.info("websocket kline thread started url=%s", url)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _handle_message(self, message: str) -> None:
        payload = json.loads(message)
        k = payload.get("k")
        if not isinstance(k, dict):
            return
        if not k.get("x"):
            return
        ts = int(k["t"])
        row = [
            float(ts),
            float(k["o"]),
            float(k["h"]),
            float(k["l"]),
            float(k["c"]),
            float(k["v"]),
        ]
        with self._lock:
            if not self._dq:
                self._dq.append(row)
                return
            last_ts = int(self._dq[-1][0])
            if ts == last_ts:
                self._dq[-1] = row
            elif ts > last_ts:
                self._dq.append(row)
