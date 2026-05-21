"""Self-contained trading monitor UI (no CDN). Polls ``/health``."""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>futures-llm-bot · 交易监控</title>
<style>
  :root {
    --bg: #0a0e14;
    --surface: #141b26;
    --surface2: #1c2636;
    --border: #2a3648;
    --text: #e8edf5;
    --muted: #8b9cb3;
    --ok: #3dd68c;
    --warn: #f5a623;
    --bad: #ff6b6b;
    --accent: #5b8def;
    --long: #3dd68c;
    --short: #ff6b6b;
    font-family: ui-sans-serif, system-ui, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); min-height: 100vh; }
  header {
    padding: 0.9rem 1.25rem; border-bottom: 1px solid var(--border);
    background: var(--surface); display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem 1rem;
  }
  h1 { margin: 0; font-size: 1.1rem; font-weight: 600; }
  .badge {
    padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.72rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .badge.ok { background: rgba(61,214,140,.18); color: var(--ok); }
  .badge.warn { background: rgba(245,166,35,.18); color: var(--warn); }
  .badge.dry { background: rgba(91,141,239,.18); color: var(--accent); }
  .meta { color: var(--muted); font-size: 0.78rem; margin-left: auto; }
  main { padding: 1rem 1.25rem 2rem; max-width: 72rem; margin: 0 auto; }
  section { margin-bottom: 1.1rem; }
  .section-title {
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 0.55rem; font-weight: 600;
  }
  .hero {
    display: grid; gap: 1rem;
    grid-template-columns: 1fr;
  }
  @media (min-width: 900px) {
    .hero { grid-template-columns: 1.2fr 1fr; }
  }
  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1rem 1.1rem;
  }
  .equity-big { font-size: 2rem; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--accent); }
  .pnl { font-size: 0.95rem; margin-top: 0.35rem; }
  .pnl.pos { color: var(--ok); }
  .pnl.neg { color: var(--bad); }
  .grid {
    display: grid; gap: 0.75rem;
    grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
  }
  .stat .label { font-size: 0.68rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .stat .val { font-size: 1.15rem; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: 0.2rem; }
  canvas#equity-chart {
    width: 100%; height: 200px; display: block; background: var(--surface2);
    border-radius: 8px; border: 1px solid var(--border);
  }
  .range-bar {
    display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0 0 0.6rem;
  }
  .range-btn {
    background: var(--surface2); color: var(--text); border: 1px solid var(--border);
    border-radius: 999px; padding: 0.2rem 0.7rem; font-size: 0.78rem;
    font-family: inherit; cursor: pointer; transition: background 0.15s, border-color 0.15s;
  }
  .range-btn:hover { border-color: var(--accent); }
  .range-btn.active { background: rgba(91,141,239,.18); color: var(--accent); border-color: var(--accent); }
  .range-meta { color: var(--muted); font-size: 0.72rem; margin-top: 0.4rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  th, td { padding: 0.45rem 0.5rem; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 0.7rem; text-transform: uppercase; }
  td.num { font-variant-numeric: tabular-nums; }
  .action-long { color: var(--long); font-weight: 600; }
  .action-short { color: var(--short); font-weight: 600; }
  .action-hold, .action-flat { color: var(--muted); }
  .decision-list { list-style: none; margin: 0; padding: 0; max-height: 220px; overflow: auto; }
  .decision-list li {
    padding: 0.55rem 0; border-bottom: 1px solid var(--border); font-size: 0.8rem; line-height: 1.35;
  }
  .decision-list .time { color: var(--muted); font-size: 0.72rem; }
  .event-list { list-style: none; margin: 0; padding: 0; max-height: 140px; overflow: auto; font-size: 0.78rem; color: var(--muted); }
  .event-list li { padding: 0.25rem 0; }
  .error {
    margin-top: 0.75rem; padding: 0.75rem; border-radius: 8px;
    background: rgba(255,107,107,.1); border: 1px solid rgba(255,107,107,.35);
    font-size: 0.82rem; display: none;
  }
  .error.visible { display: block; }
  .links { margin-top: 1rem; font-size: 0.78rem; color: var(--muted); }
  .links a { color: var(--accent); text-decoration: none; }
  .empty { color: var(--muted); font-size: 0.82rem; padding: 0.5rem 0; }
  .pick-banner {
    margin-top: 0.65rem; padding: 0.55rem 0.75rem; border-radius: 8px;
    background: rgba(91,141,239,.12); border: 1px solid rgba(91,141,239,.35); font-size: 0.82rem;
  }
  .probe-row {
    display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center;
  }
  .probe-input {
    flex: 1; min-width: 10rem; padding: 0.45rem 0.65rem; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface2); color: var(--text);
    font-family: inherit; font-size: 0.88rem;
  }
  .probe-btn {
    padding: 0.45rem 1rem; border-radius: 8px; border: 1px solid var(--accent);
    background: rgba(91,141,239,.2); color: var(--accent); font-weight: 600;
    font-family: inherit; font-size: 0.85rem; cursor: pointer;
  }
  .probe-btn:disabled { opacity: 0.5; cursor: wait; }
  .probe-result {
    margin-top: 0.75rem; padding: 0.75rem; border-radius: 8px;
    background: var(--surface2); border: 1px solid var(--border); font-size: 0.85rem;
    line-height: 1.45; display: none;
  }
  .probe-result.visible { display: block; }
  .probe-advice { font-size: 1.35rem; font-weight: 700; margin-bottom: 0.35rem; }
  .probe-advice.long { color: var(--long); }
  .probe-advice.short { color: var(--short); }
  .probe-advice.watch { color: var(--muted); }
  .probe-hint { color: var(--muted); font-size: 0.75rem; margin-top: 0.35rem; }
  .probe-timing {
    margin-top: 0.75rem; padding-top: 0.65rem; border-top: 1px solid var(--border);
  }
  .probe-timing-title { font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.5rem; }
  .probe-timing-item { margin-bottom: 0.65rem; font-size: 0.82rem; line-height: 1.4; }
  .probe-timing-item:last-child { margin-bottom: 0; }
  .probe-timing-item .side-long { color: var(--long); font-weight: 600; }
  .probe-timing-item .side-short { color: var(--short); font-weight: 600; }
  .probe-timing-trigger { color: var(--text); margin-top: 0.2rem; }
  .probe-timing-summary { color: var(--muted); font-size: 0.78rem; margin-top: 0.15rem; }
</style>
</head>
<body>
<header>
  <h1>futures-llm-bot</h1>
  <span id="health-badge" class="badge ok">—</span>
  <span id="dry-badge" class="badge dry" style="display:none">DRY RUN</span>
  <span class="meta">v<span id="ver">—</span> · 运行 <span id="up">—</span>s · 刷新 <span id="ts">—</span></span>
</header>
<main>
  <div class="hero">
    <section class="card">
      <div class="section-title">账户总览</div>
      <div class="equity-big">$<span id="equity">—</span></div>
      <div class="pnl" id="day-pnl">今日盈亏 —</div>
      <div class="grid" style="margin-top:0.85rem">
        <div class="stat"><div class="label">可用保证金</div><div class="val" id="avail">—</div></div>
        <div class="stat"><div class="label">未实现盈亏</div><div class="val" id="upnl">—</div></div>
        <div class="stat"><div class="label">今日交易笔数</div><div class="val" id="trades-today">—</div></div>
        <div class="stat"><div class="label">今日回撤</div><div class="val" id="day-dd">—</div></div>
      </div>
    </section>
    <section class="card">
      <div class="section-title">资产曲线（北京时间）</div>
      <div class="range-bar" id="range-bar">
        <button class="range-btn" data-range="5m">5 分</button>
        <button class="range-btn" data-range="15m">15 分</button>
        <button class="range-btn active" data-range="1h">1 时</button>
        <button class="range-btn" data-range="6h">6 时</button>
        <button class="range-btn" data-range="1d">1 天</button>
        <button class="range-btn" data-range="1w">1 周</button>
        <button class="range-btn" data-range="1m">1 月</button>
        <button class="range-btn" data-range="all">全部</button>
      </div>
      <canvas id="equity-chart" width="640" height="200"></canvas>
      <div class="range-meta" id="range-meta">—</div>
    </section>
  </div>

  <section>
    <div class="section-title">手动诊币（仅分析，不下单）</div>
    <div class="card">
      <div class="probe-row">
        <input class="probe-input" id="probe-symbol" type="text" placeholder="输入币种，如 DOGE、BTCUSDT、BTC/USDT:USDT" autocomplete="off"/>
        <button type="button" class="probe-btn" id="probe-btn">分析信号</button>
      </div>
      <p class="probe-hint">使用当前机器人策略（与自动交易相同规则），返回做多 / 做空 / 观望；观望时会附带做多/做空时机参考，不会下单。</p>
      <div id="probe-result" class="probe-result"></div>
    </div>
  </section>

  <section>
    <div class="section-title">运行配置</div>
    <div class="card grid" id="config-grid"></div>
  </section>

  <section id="pick-section" style="display:none">
    <div class="section-title">本轮优选</div>
    <div class="card"><div id="pick-banner" class="pick-banner">—</div></div>
  </section>

  <section>
    <div class="section-title">当前持仓</div>
    <div class="card">
      <table>
        <thead><tr><th>交易对</th><th>方向</th><th>数量</th><th>名义</th><th>未实现盈亏</th></tr></thead>
        <tbody id="positions-body"><tr><td colspan="5" class="empty">暂无持仓</td></tr></tbody>
      </table>
    </div>
  </section>

  <section id="signals-section" style="display:none">
    <div class="section-title">候选池信号</div>
    <div class="card">
      <table>
        <thead><tr><th>交易对</th><th>动作</th><th>置信度</th><th>仓位%</th><th>原因</th></tr></thead>
        <tbody id="signals-body"></tbody>
      </table>
    </div>
  </section>

  <div class="hero">
    <section class="card">
      <div class="section-title">最近决策</div>
      <ul class="decision-list" id="decisions"></ul>
    </section>
    <section class="card">
      <div class="section-title">运行指标</div>
      <div class="grid">
        <div class="stat"><div class="label">Tick 尝试</div><div class="val" id="ticks-att">0</div></div>
        <div class="stat"><div class="label">成功</div><div class="val" id="ticks-ok">0</div></div>
        <div class="stat"><div class="label">失败</div><div class="val" id="ticks-fail">0</div></div>
        <div class="stat"><div class="label">风控拦截</div><div class="val" id="ticks-block">0</div></div>
        <div class="stat"><div class="label">实盘下单</div><div class="val" id="orders">0</div></div>
        <div class="stat"><div class="label">LLM 调用</div><div class="val" id="llm-calls">0</div></div>
      </div>
    </section>
  </div>

  <section>
    <div class="section-title">事件</div>
    <div class="card"><ul class="event-list" id="events"></ul></div>
  </section>

  <div id="err" class="error"></div>
  <p class="links">接口: <a href="/health">/health</a> · <a href="/api/status">/api/status</a> · <a href="/api/equity?range=1d">/api/equity</a> · <a href="/api/signal?symbol=BTC">/api/signal</a> · <a href="/metrics">/metrics</a></p>
</main>
<script>
(function () {
  const el = (id) => document.getElementById(id);
  let currentRange = "1h";
  let lastRangeFetchAt = 0;
  const TZ = "Asia/Shanghai";
  function fmt(n, d) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    return n.toFixed(d == null ? 2 : d);
  }
  function fmtTime(iso, compact) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso).slice(0, 19);
      const opts = {
        timeZone: TZ,
        year: compact ? undefined : "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
      };
      if (compact) delete opts.year;
      return d.toLocaleString("zh-CN", opts).replace(/\//g, "-");
    } catch (e) {
      return String(iso).slice(0, 19);
    }
  }
  function nowDisplay() {
    return fmtTime(new Date().toISOString(), true);
  }
  function actionClass(a) {
    a = (a || "").toLowerCase();
    if (a === "long") return "action-long";
    if (a === "short") return "action-short";
    return "action-hold";
  }
  function drawEquity(points) {
    const c = el("equity-chart");
    const ctx = c.getContext("2d");
    const w = c.width, h = c.height;
    ctx.clearRect(0, 0, w, h);
    if (!points || points.length < 2) {
      ctx.fillStyle = "#8b9cb3";
      ctx.font = "13px sans-serif";
      ctx.fillText("等待更多数据点…", 16, h / 2);
      return;
    }
    const vals = points.map((p) => p.v);
    let min = Math.min.apply(null, vals);
    let max = Math.max.apply(null, vals);
    if (min === max) { min *= 0.99; max *= 1.01; }
    const pad = 24;
    ctx.strokeStyle = "#2a3648";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad, h - pad);
    ctx.lineTo(w - pad, h - pad);
    ctx.stroke();
    ctx.strokeStyle = "#5b8def";
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((p, i) => {
      const x = pad + (i / (points.length - 1)) * (w - 2 * pad);
      const y = h - pad - ((p.v - min) / (max - min)) * (h - 2 * pad);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = "#8b9cb3";
    ctx.font = "11px sans-serif";
    ctx.fillText(fmt(min, 2), pad, h - 6);
    ctx.fillText(fmt(max, 2), pad, 14);
  }
  function renderConfig(cfg) {
    const items = [
      ["模式", cfg.symbol_mode],
      ["信号", cfg.signal_source + (cfg.strategy_name ? " / " + cfg.strategy_name : "")],
      ["周期", cfg.timeframe],
      ["仓位", cfg.position_sizing + " · " + cfg.leverage + "x"],
      ["上限", cfg.max_notional_usdt + " USDT"],
      ["候选", cfg.symbol_candidates || cfg.symbol],
    ];
    el("config-grid").innerHTML = items.map(([k, v]) =>
      '<div class="stat"><div class="label">' + k + '</div><div class="val">' + (v ?? "—") + '</div></div>'
    ).join("");
  }
  async function poll() {
    try {
      const r = await fetch("/health", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      const st = j.status || "unknown";
      const hb = el("health-badge");
      hb.textContent = st === "healthy" ? "正常" : "降级";
      hb.className = "badge " + (st === "healthy" ? "ok" : "warn");
      el("ver").textContent = j.version || "—";
      el("up").textContent = typeof j.uptime_s === "number" ? j.uptime_s.toFixed(0) : "—";
      el("ts").textContent = nowDisplay();
      const d = j.dashboard || {};
      const cfg = d.config || {};
      const dry = !!cfg.dry_run;
      el("dry-badge").style.display = dry ? "inline-block" : "none";
      renderConfig(cfg);
      const acc = d.account || {};
      el("equity").textContent = fmt(acc.equity_usdt, 2);
      const pnl = acc.day_pnl_usdt;
      const pnlEl = el("day-pnl");
      if (typeof pnl === "number") {
        const sign = pnl >= 0 ? "+" : "";
        const pct = acc.day_pnl_pct != null ? " (" + sign + acc.day_pnl_pct + "%)" : "";
        pnlEl.textContent = "今日盈亏 " + sign + fmt(pnl, 2) + " USDT" + pct;
        pnlEl.className = "pnl " + (pnl >= 0 ? "pos" : "neg");
      } else {
        pnlEl.textContent = "今日盈亏 —";
        pnlEl.className = "pnl";
      }
      el("avail").textContent = fmt(acc.available_margin_usdt, 2);
      el("upnl").textContent = fmt(acc.unrealized_pnl_usdt, 2);
      const sess = d.session || {};
      el("trades-today").textContent = (sess.trade_count ?? "—") + (sess.max_trades_per_day > 0 ? " / " + sess.max_trades_per_day : "");
      el("day-dd").textContent = fmt(sess.day_drawdown_usdt, 2);
      // Only redraw equity from /health when on the default (1h) range; longer
      // ranges are served by /api/equity and re-fetched on selection / timer.
      if (currentRange === "1h") {
        drawEquity(d.equity_history || []);
        el("range-meta").textContent = "样本 " + (d.equity_history || []).length +
          " / 总记录 " + (d.equity_history_total ?? "—");
      }
      const pos = d.positions || [];
      const pb = el("positions-body");
      if (!pos.length) {
        pb.innerHTML = '<tr><td colspan="5" class="empty">暂无持仓</td></tr>';
      } else {
        pb.innerHTML = pos.map((p) => '<tr><td>' + (p.symbol || "—") + '</td><td class="' + actionClass(p.side) + '">' +
          (p.side || "—") + '</td><td class="num">' + fmt(p.contracts, 4) + '</td><td class="num">' +
          fmt(p.notional, 2) + '</td><td class="num">' + fmt(p.unrealized_pnl, 2) + '</td></tr>').join("");
      }
      const cands = d.candidates || [];
      const sigs = d.signals || {};
      const sigSec = el("signals-section");
      if (cands.length && Object.keys(sigs).length) {
        sigSec.style.display = "block";
        el("signals-body").innerHTML = cands.map((sym) => {
          const s = sigs[sym] || {};
          return '<tr><td>' + sym + '</td><td class="' + actionClass(s.action) + '">' + (s.action || "—") +
            '</td><td class="num">' + fmt(s.confidence, 2) + '</td><td class="num">' + fmt(s.size_pct, 1) +
            '</td><td>' + (s.reason || "").slice(0, 80) + '</td></tr>';
        }).join("");
      } else {
        sigSec.style.display = "none";
      }
      const pick = d.pick;
      const pickSec = el("pick-section");
      if (pick && pick.symbol) {
        pickSec.style.display = "block";
        const ps = pick.signal || {};
        el("pick-banner").textContent = pick.symbol + " · " + (ps.action || "") +
          " · 置信度 " + fmt(ps.confidence, 2) + " · 得分 " + fmt(pick.score, 3);
      } else {
        pickSec.style.display = "none";
      }
      const dec = d.decisions || [];
      const dl = el("decisions");
      if (!dec.length) {
        dl.innerHTML = '<li class="empty">暂无决策记录</li>';
      } else {
        dl.innerHTML = dec.slice(0, 20).map((x) => {
          const s = x.signal || {};
          return '<li><span class="time">' + fmtTime(x.at, true) + '</span> · ' + (x.symbol || "") +
            ' · <span class="' + actionClass(s.action) + '">' + (s.action || "") + '</span> · ' +
            (x.outcome || "") + (x.detail ? " · " + x.detail : "") + '</li>';
        }).join("");
      }
      const ev = d.events || [];
      el("events").innerHTML = ev.length ? ev.slice(0, 30).map((e) =>
        '<li><span class="time">' + fmtTime(e.at, true) + '</span> ' + (e.message || "") + '</li>'
      ).join("") : '<li class="empty">暂无事件</li>';
      const t = j.ticks || {};
      el("ticks-att").textContent = t.attempted ?? 0;
      el("ticks-ok").textContent = t.completed ?? 0;
      el("ticks-fail").textContent = t.failed ?? 0;
      el("ticks-block").textContent = t.risk_or_session_blocked ?? 0;
      el("orders").textContent = (j.orders && j.orders.real_submitted) ?? 0;
      el("llm-calls").textContent = (j.llm && j.llm.calls) ?? 0;
      const er = el("err");
      if (j.last_error) {
        er.textContent = "last_error: " + j.last_error;
        er.classList.add("visible");
      } else {
        er.textContent = "";
        er.classList.remove("visible");
      }
    } catch (e) {
      el("health-badge").textContent = "错误";
      el("health-badge").className = "badge warn";
      const er = el("err");
      er.textContent = String(e);
      er.classList.add("visible");
    }
  }
  async function fetchRange(r) {
    try {
      const resp = await fetch("/api/equity?range=" + encodeURIComponent(r), { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const j = await resp.json();
      drawEquity(j.points || []);
      el("range-meta").textContent = "范围 " + (j.range || r) +
        " · 样本 " + (j.points || []).length +
        " · 原始 " + (j.raw_count ?? "—") + " 个点";
      lastRangeFetchAt = Date.now();
    } catch (e) {
      el("range-meta").textContent = "加载失败: " + e;
    }
  }
  function setRange(r) {
    currentRange = r;
    document.querySelectorAll(".range-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.range === r);
    });
    if (r === "1h") {
      // 1h uses the embedded /health payload; let next poll() draw it.
      el("range-meta").textContent = "范围 1h · 等待刷新…";
    } else {
      fetchRange(r);
    }
  }
  document.querySelectorAll(".range-btn").forEach((b) => {
    b.addEventListener("click", () => setRange(b.dataset.range));
  });
  async function runProbe() {
    const sym = (el("probe-symbol").value || "").trim();
    const box = el("probe-result");
    const btn = el("probe-btn");
    if (!sym) {
      box.className = "probe-result visible";
      box.innerHTML = '<span class="probe-hint">请先输入币种</span>';
      return;
    }
    btn.disabled = true;
    box.className = "probe-result visible";
    box.innerHTML = '<span class="probe-hint">分析中…</span>';
    try {
      const resp = await fetch("/api/signal?symbol=" + encodeURIComponent(sym), { cache: "no-store" });
      const j = await resp.json();
      if (!j.ok) {
        box.innerHTML = '<span style="color:var(--bad)">' + (j.error || ("HTTP " + resp.status)) + '</span>';
        return;
      }
      const cls = j.advice || "watch";
      let html = '<div class="probe-advice ' + cls + '">' + (j.advice_cn || "—") + '</div>';
      html += '<div><strong>' + (j.symbol || "") + '</strong> · 动作 <span class="' + actionClass(j.action) + '">' +
        (j.action_cn || j.action || "") + '</span></div>';
      html += '<div>置信度 ' + fmt(j.confidence, 2) + ' · 仓位 ' + fmt(j.size_pct, 0) + '% · ' +
        (j.strategy_label || j.source || "") + ' · ' + (j.timeframe || "") + '</div>';
      html += '<div style="margin-top:0.35rem;color:var(--muted)">' + (j.reason || "—") + '</div>';
      if (j.risk_message) {
        html += '<div style="margin-top:0.35rem;color:var(--warn)">风控: ' + j.risk_message + '</div>';
      }
      const hints = j.timing_hints || [];
      if ((j.advice === "watch" || j.action === "hold") && hints.length) {
        html += '<div class="probe-timing"><div class="probe-timing-title">观望 · 时机参考</div>';
        hints.forEach((h) => {
          const sideCls = h.side === "long" ? "side-long" : "side-short";
          html += '<div class="probe-timing-item"><span class="' + sideCls + '">' + (h.title || "") +
            '</span><div class="probe-timing-trigger">' + (h.trigger || "") + '</div>' +
            '<div class="probe-timing-summary">' + (h.summary || "") + '</div></div>';
        });
        html += '</div>';
      }
      html += '<div class="probe-hint">' + (j.at_display || j.at || "") +
        (j.would_trade ? " · 若自动交易且通过风控会下单" : " · 仅观望/未达置信度，不会自动下单") + '</div>';
      box.innerHTML = html;
    } catch (e) {
      box.innerHTML = '<span style="color:var(--bad)">请求失败: ' + e + '</span>';
    } finally {
      btn.disabled = false;
    }
  }
  el("probe-btn").addEventListener("click", runProbe);
  el("probe-symbol").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") runProbe();
  });
  poll();
  setInterval(poll, 3000);
  // Re-fetch longer ranges every 30 s so the chart stays current.
  setInterval(() => {
    if (currentRange !== "1h" && Date.now() - lastRangeFetchAt > 25000) {
      fetchRange(currentRange);
    }
  }, 5000);
})();
</script>
</body>
</html>
"""
