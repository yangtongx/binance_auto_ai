"""HTTP server: dashboard UI, ``/health`` JSON, and Prometheus ``/metrics``."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from futures_llm_bot import metrics
from futures_llm_bot.dashboard_html import DASHBOARD_HTML

logger = logging.getLogger(__name__)

# Back-compat for tests importing ``_DASHBOARD_HTML``.
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
                # Browser/curl closed early; ignore (common for /health polls).
                pass

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path or "/"
            if path in ("/", "/dashboard"):
                self._send_body(200, _DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path in ("/health", "/api/status"):
                body = json.dumps(metrics.snapshot(), indent=2).encode("utf-8")
                self._send_body(200, body, "application/json; charset=utf-8")
            elif path == "/metrics":
                body = metrics.prometheus_text().encode("utf-8")
                self._send_body(200, body, "text/plain; charset=utf-8")
            else:
                self.send_error(404, "Not Found")

    def _run() -> None:
        server = HTTPServer((host, port), _Handler)
        logger.info(
            "observability listening on http://%s:%s (/, /dashboard, /health, /api/status, /metrics)",
            host,
            port,
        )
        server.serve_forever()

    t = threading.Thread(target=_run, name="observability-http", daemon=True)
    t.start()
    return t
