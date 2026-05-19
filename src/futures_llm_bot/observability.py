"""Minimal HTTP server: ``/health`` (JSON) and ``/metrics`` (Prometheus text)."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from futures_llm_bot import metrics

logger = logging.getLogger(__name__)

# Self-contained UI (no CDN): polls ``/health`` on the same host/port.
_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>futures-llm-bot · dashboard</title>
<style>
  :root {
    --bg: #0f1419;
    --surface: #1a2332;
    --border: #2d3a4d;
    --text: #e7ecf3;
    --muted: #8b9cb3;
    --ok: #3dd68c;
    --warn: #f5a623;
    --bad: #ff6b6b;
    --accent: #5b8def;
    font-family: ui-sans-serif, system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); min-height: 100vh; }
  header {
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--border);
    display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem 1.5rem;
    background: var(--surface);
  }
  h1 { margin: 0; font-size: 1.15rem; font-weight: 600; letter-spacing: -0.02em; }
  .status {
    padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.06em;
  }
  .status.healthy { background: rgba(61, 214, 140, 0.2); color: var(--ok); }
  .status.degraded { background: rgba(245, 166, 35, 0.2); color: var(--warn); }
  .meta { color: var(--muted); font-size: 0.8rem; margin-left: auto; }
  main { padding: 1.25rem; max-width: 56rem; margin: 0 auto; }
  .grid {
    display: grid; gap: 0.85rem;
    grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  }
  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 1rem 1.1rem;
  }
  .card h2 { margin: 0 0 0.65rem; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; }
  .big { font-size: 1.65rem; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--accent); }
  .sub { font-size: 0.8rem; color: var(--muted); margin-top: 0.35rem; line-height: 1.4; }
  .error {
    margin-top: 1rem; padding: 0.85rem 1rem; border-radius: 8px; background: rgba(255, 107, 107, 0.12);
    border: 1px solid rgba(255, 107, 107, 0.35); font-size: 0.85rem; word-break: break-word;
    display: none;
  }
  .error.visible { display: block; }
  .links { margin-top: 1.25rem; font-size: 0.8rem; color: var(--muted); }
  .links a { color: var(--accent); text-decoration: none; }
  .links a:hover { text-decoration: underline; }
</style>
</head>
<body>
<header>
  <h1>futures-llm-bot</h1>
  <span id="badge" class="status healthy">—</span>
  <span class="meta">v<span id="ver">—</span> · up <span id="up">—</span>s · updated <span id="ts">—</span></span>
</header>
<main>
  <div class="grid">
    <div class="card"><h2>Ticks</h2><div class="big" id="ticks-att">0</div><div class="sub">attempted</div></div>
    <div class="card"><h2>Completed</h2><div class="big" id="ticks-ok">0</div><div class="sub">successful ticks</div></div>
    <div class="card"><h2>Failed</h2><div class="big" id="ticks-fail">0</div><div class="sub">exceptions</div></div>
    <div class="card"><h2>Risk blocked</h2><div class="big" id="ticks-block">0</div><div class="sub">risk / session</div></div>
    <div class="card"><h2>Real orders</h2><div class="big" id="orders">0</div><div class="sub">submitted</div></div>
    <div class="card"><h2>LLM calls</h2><div class="big" id="llm-calls">0</div><div class="sub">avg <span id="llm-ms">0</span> ms</div></div>
    <div class="card"><h2>LLM failures</h2><div class="big" id="llm-fail">0</div><div class="sub">after retries</div></div>
  </div>
  <div id="err" class="error"></div>
  <p class="links">Raw: <a href="/health">/health</a> · <a href="/metrics">/metrics</a></p>
</main>
<script>
(function () {
  const el = (id) => document.getElementById(id);
  function fmtUptime(n) {
    return typeof n === "number" ? (Math.round(n * 1000) / 1000).toFixed(3).replace(/\.?0+$/, "") : "0";
  }
  function fmtMs(n) {
    return typeof n === "number" ? (Math.round(n * 100) / 100).toFixed(2) : "0";
  }
  async function poll() {
    try {
      const r = await fetch("/health", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      const st = j.status || "unknown";
      const b = el("badge");
      b.textContent = st;
      b.className = "status " + (st === "healthy" ? "healthy" : "degraded");
      el("ver").textContent = j.version || "—";
      el("up").textContent = fmtUptime(j.uptime_s);
      el("ts").textContent = new Date().toISOString().slice(11, 19) + "Z";
      const t = j.ticks || {};
      el("ticks-att").textContent = t.attempted ?? 0;
      el("ticks-ok").textContent = t.completed ?? 0;
      el("ticks-fail").textContent = t.failed ?? 0;
      el("ticks-block").textContent = t.risk_or_session_blocked ?? 0;
      el("orders").textContent = (j.orders && j.orders.real_submitted) ?? 0;
      const L = j.llm || {};
      el("llm-calls").textContent = L.calls ?? 0;
      el("llm-ms").textContent = fmtMs(L.avg_duration_ms);
      el("llm-fail").textContent = L.failures ?? 0;
      const er = el("err");
      if (j.last_error) { er.textContent = "last_error: " + j.last_error; er.classList.add("visible"); }
      else { er.textContent = ""; er.classList.remove("visible"); }
    } catch (e) {
      el("badge").textContent = "error";
      el("badge").className = "status degraded";
      const er = el("err");
      er.textContent = String(e);
      er.classList.add("visible");
    }
  }
  poll();
  setInterval(poll, 2500);
})();
</script>
</body>
</html>
"""


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
            elif path == "/health":
                body = json.dumps(metrics.snapshot(), indent=2).encode("utf-8")
                self._send_body(200, body, "application/json; charset=utf-8")
            elif path == "/metrics":
                body = metrics.prometheus_text().encode("utf-8")
                self._send_body(200, body, "text/plain; charset=utf-8")
            else:
                self.send_error(404, "Not Found")

    def _run() -> None:
        server = HTTPServer((host, port), _Handler)
        logger.info("observability listening on http://%s:%s (/, /dashboard, /health, /metrics)", host, port)
        server.serve_forever()

    t = threading.Thread(target=_run, name="observability-http", daemon=True)
    t.start()
    return t
