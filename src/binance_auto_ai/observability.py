"""监控 HTTP 服务：面板 HTML、/health、/api/equity、/api/signal、Prometheus /metrics。"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from binance_auto_ai import dashboard_state, metrics
from binance_auto_ai.config import Settings
from binance_auto_ai.dashboard_html import DASHBOARD_HTML
from binance_auto_ai.signal_probe import evaluate_symbol_signal

logger = logging.getLogger(__name__)

# 兼容测试导入 ``_DASHBOARD_HTML``
_DASHBOARD_HTML = DASHBOARD_HTML


def start_observability_background(host: str, port: int) -> threading.Thread:
    """Start daemon thread; safe to call once at bot startup."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_body(self, code: int, body: bytes, content_type: str) -> None:
            try:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # 浏览器/curl 提前断开；忽略（/health 轮询常见）
                pass

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path in ("/", "/dashboard"):
                self._send_body(200, _DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path in ("/health", "/api/status"):
                body = json.dumps(metrics.snapshot(), indent=2).encode("utf-8")
                self._send_body(200, body, "application/json; charset=utf-8")
            elif path == "/api/equity":
                qs = parse_qs(parsed.query)
                range_key = (qs.get("range") or ["1h"])[0]
                payload = dashboard_state.equity_range(range_key)
                body = json.dumps(payload).encode("utf-8")
                self._send_body(200, body, "application/json; charset=utf-8")
            elif path == "/api/signal":
                qs = parse_qs(parsed.query)
                symbol_raw = (qs.get("symbol") or [""])[0].strip()
                try:
                    settings = Settings()
                    result = evaluate_symbol_signal(settings, symbol_raw)
                    payload = result.to_dict()
                    code = 200 if result.ok else 400
                except Exception as e:
                    logger.exception("api/signal failed")
                    payload = {"ok": False, "error": str(e), "symbol_input": symbol_raw}
                    code = 500
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send_body(code, body, "application/json; charset=utf-8")
            elif path == "/metrics":
                body = metrics.prometheus_text().encode("utf-8")
                self._send_body(200, body, "text/plain; charset=utf-8")
            else:
                self.send_error(404, "Not Found")

    def _run() -> None:
        server = HTTPServer((host, port), _Handler)
        logger.info(
            "observability listening on http://%s:%s (/, /dashboard, /health, /api/status, /api/equity, /api/signal, /metrics)",
            host,
            port,
        )
        server.serve_forever()

    t = threading.Thread(target=_run, name="observability-http", daemon=True)
    t.start()
    return t
