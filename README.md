# futures-llm-bot

**Languages:** [English](README.md) · [中文](README.zh.md)

**futures-llm-bot** is a Python application for **Binance USDT-M (USDⓈ-M) linear perpetual futures**. It runs a periodic loop: pull market data and account state, turn them into trade **signals**, apply **risk** and **session** limits, then place orders through **CCXT** in either **one-way** or **hedge** position mode.

You can drive signals in two ways:

1. **`SIGNAL_SOURCE=strategy`** — deterministic technical rules (same implementations as the bundled backtester): SMA cross, RSI, MACD, Bollinger, Ichimoku-style cloud, Fibonacci pullback reclaim, volume-profile POC breakout, **Stochastic**, **ATR breakout**, and optional **ML** (TorchScript / Keras).
2. **`SIGNAL_SOURCE=llm`** — send OHLCV plus **account context** (positions, wallet, mode) to an **OpenAI-compatible** chat API (e.g. OpenAI, DeepSeek, Azure) and parse a strict JSON signal.

The project also includes a **teaching backtest** (simplified PnL model), a **real exchange PnL** summarizer (`futures-llm-real-pnl`), optional **HTTP observability** with a small **dashboard**, and **pytest** coverage for core paths.

> **Disclaimer:** This is **experimental** software. Futures are **high risk**. Prefer **testnet** and **`DRY_RUN=true`** until you fully understand behavior. You alone are responsible for API keys, configuration, and losses. The bundled backtest is **not** a substitute for exchange-reported PnL.

---

## Features

| Area | What you get |
|------|----------------|
| **Execution** | Binance USDM via `ccxt.binanceusdm`, testnet/mainnet, one-way vs hedge handling |
| **Signals** | Rule strategies aligned with `futures-llm-backtest`, or LLM JSON output validated to `LLMSignal` |
| **Live WS (optional)** | `USE_WEBSOCKET=true`: REST-seeded + Binance **closed** kline stream, exponential backoff reconnect (`WS_RECONNECT_*`) |
| **Telegram (optional)** | Named templates or custom `TELEGRAM_MESSAGE_TEMPLATE`; JSON `sendMessage` + optional `TELEGRAM_PARSE_MODE` |
| **ML (optional)** | `STRATEGY_NAME=ml`: TorchScript (`ML_TORCH_ARCH=mlp\|lstm\|transformer`) or Keras flat MLP; **`ML_HOT_RELOAD`** watches `ML_MODEL_PATH` mtime (throttled) |
| **ML training / ops** | `examples/train_ml_torch.py` (CSV / **paginated `--fetch`**); **`examples/cron_retrain_4h.sh`** for periodic retrain + atomic replace |
| **Risk** | `MIN_CONFIDENCE`, notional caps (`MAX_NOTIONAL_USDT`), optional daily trade cap and daily loss cap (UTC) |
| **Session state** | JSON `STATE_FILE` with `filelock` for multi-process safety |
| **Backtest** | CSV or CCXT fetch; **close-to-close** approximation + fees (`fee_bps`); **not** full funding/leverage simulation |
| **Real PnL** | Summarize `REALIZED_PNL`, `FUNDING_FEE`, `COMMISSION` from Binance `/fapi/v1/income` |
| **Observability** | Optional `GET /`, `/dashboard`, `/health`, `/metrics` on `OBSERVABILITY_HOST:PORT` |
| **Dev UX** | Pydantic settings, `pyright` paths in `pyproject.toml`, smoke CLI flag |

---

## Architecture (short)

1. **`cli.run_loop`** waits for the next 1m boundary (unless `--once`), then executes one **tick**.
2. **Tick** fetches **USDT equity** and **positions**. **OHLCV** comes from **`fetch_ohlcv`** or, if **`USE_WEBSOCKET=true`** (strategy mode only), from a thread-safe **`BinanceUsdMKlineBuffer`** fed by closed klines; buffer may fall back to REST if too short.
3. After a signal is produced, **`telegram_notify`** may send a **templated** message (if `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` are set).
4. **`risk.assess_signal`** filters low-confidence/size signals; **`session_risk`** may block new long/short for the UTC day.
5. **`execution`** resolves hedge mode, converts signals to orders via **`order_utils`**, and records metrics on real submissions.

For a diagram and module table, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Requirements

- **Python** ≥ 3.10  
- **Binance** API key with **USDT-M futures** permission if not in `DRY_RUN` (withdrawal should stay disabled on the key)  
- **`OPENAI_API_KEY`** only when **`SIGNAL_SOURCE=llm`**

---

## Installation

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Unix
source .venv/bin/activate

pip install -e ".[dev]"
copy .env.example .env   # Windows — use cp on Unix
```

**Optional dependency groups** (install only what you need):

| Extra | Install | Purpose |
|-------|---------|---------|
| *(default)* | `pip install -e .` | Core bot + backtest |
| `dev` | `pip install -e ".[dev]"` | `pytest` |
| `realtime` | `pip install -e ".[realtime]"` | `websocket-client` for **`USE_WEBSOCKET`** |
| `ml-torch` | `pip install -e ".[ml-torch]"` | PyTorch for **TorchScript** ML inference + **training example** |
| `ml-tf` | `pip install -e ".[ml-tf]"` | TensorFlow/Keras for **flat** ML models only |

Editable install exposes console scripts:

| Command | Purpose |
|---------|---------|
| `futures-llm-bot` | Main trading loop |
| `futures-llm-backtest` | Rule backtest on CSV or `--fetch` |
| `futures-llm-real-pnl` | Binance income history summary |

Without `pip install -e .`, set **`PYTHONPATH=src`** before `python -m futures_llm_bot`.

---

## Docker (Tencent CNB / Kubernetes / container hosts)

The repo includes a **`Dockerfile`**. **Do not** put API keys in the image or Git: configure **`BINANCE_API_KEY`**, **`BINANCE_API_SECRET`**, **`OPENAI_API_KEY`**, **`OPENAI_BASE_URL`**, **`OPENAI_MODEL`**, and the rest as **runtime environment variables** (CNB/K8s secrets, platform “环境变量”, etc.).

```bash
docker build -t futures-llm-bot:local .
docker run --rm \
  -e BINANCE_API_KEY -e BINANCE_API_SECRET \
  -e OPENAI_API_KEY -e OPENAI_BASE_URL=https://api.deepseek.com -e OPENAI_MODEL=deepseek-v4-pro \
  -e SIGNAL_SOURCE=llm -e BINANCE_TESTNET=true -e DRY_RUN=true \
  -v bot-state:/data \
  futures-llm-bot:local
```

Volume **`/data`** persists session risk state (`STATE_FILE` defaults to `/data/.futures_llm_bot_state.json` in the image). Use **`futures-llm-real-pnl`** / **`futures-llm-backtest`** in CI or a sidecar only if you add those to the image (`pip install` already includes entry points).

On **[cnb.cool](https://cnb.cool)** (or Tencent TKE): connect this repository, build from the `Dockerfile`, push to your registry, run the container with secrets injected in the console — **never** commit `.env` or keys.

---

## Configuration

Copy **`.env.example`** → **`.env`** (loaded from repo root). Important groups:

- **Binance:** `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `BINANCE_TESTNET`  
- **LLM (when `SIGNAL_SOURCE=llm`):** `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, `OPENAI_MODEL`, timeouts/retries  
- **Trading:** `SYMBOL` (e.g. `BTC/USDT:USDT`), `TIMEFRAME`, `KLINES_LIMIT`, `MAX_NOTIONAL_USDT`, `DRY_RUN`, `MIN_CONFIDENCE`  
- **Signals — rules:** `STRATEGY_NAME` and matching `STRATEGY_*` / Ichimoku / Fib / VP / Stoch / ATR / ML fields (**see [Strategies](#strategies-rules) and `.env.example`**)  
- **WebSocket (optional):** `USE_WEBSOCKET`, `WS_RECONNECT_BASE_SEC`, `WS_RECONNECT_MAX_SEC`, `WS_RECONNECT_JITTER` (requires `.[realtime]`; **strategy** mode only)  
- **Telegram (optional):** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_TEMPLATE`, `TELEGRAM_MESSAGE_TEMPLATE`, `TELEGRAM_PARSE_MODE`  
- **ML (optional):** `ML_BACKEND`, `ML_MODEL_PATH`, `STRATEGY_ML_WINDOW`, `ML_TORCH_ARCH`; **`ML_HOT_RELOAD`** (default `true`), **`ML_HOT_RELOAD_INTERVAL_SEC`** (default `30`, seconds between mtime checks when `STRATEGY_NAME=ml`)  
- **Position / HTTP:** `POSITION_MODE`, `EXCHANGE_TIMEOUT_MS`, `POSITION_POLL_*`  
- **Session risk:** `MAX_TRADES_PER_DAY`, `MAX_DAILY_LOSS_USDT`, `STATE_FILE`, `DAILY_LOSS_WARN_RATIO`  
- **Observability:** `OBSERVABILITY_HOST`, `OBSERVABILITY_PORT` (non-zero enables HTTP UI + JSON + Prometheus text)

`FLAT` / `HOLD` are **not** blocked by daily trade or loss limits so you can still reduce risk.

---

## Running the bot

```bash
futures-llm-bot              # loop (waits for candle boundary)
futures-llm-bot --once       # single tick, then exit
futures-llm-bot --smoke      # load settings + imports only; no API calls
```

As a module:

```bash
python -m futures_llm_bot --once
```

---

## Signal sources

### Rule mode (`SIGNAL_SOURCE=strategy`, default in `.env.example`)

- Uses **`strategy_factory.build_live_strategy`** — same strategy classes as the backtester.  
- **`OPENAI_API_KEY`** is **not** required.  
- **`STRATEGY_NAME`** must match a registered id; parameters mirror **`futures-llm-backtest`** (SMA/RSI/MACD/BB/Ichimoku/Fib/VP/Stoch/ATR/ML — see **[Strategies](#strategies-rules)**).

### LLM mode (`SIGNAL_SOURCE=llm`)

- Builds a text **prompt** with recent OHLCV (tail) and **formatted account context**.  
- Calls **`llm_strategy.llm_decide`** with retries on transient API errors; parses JSON into **`LLMSignal`**.  
- Compatible with **DeepSeek** and other OpenAI-style endpoints via `OPENAI_BASE_URL`.

---

## Strategies (rules)

| `STRATEGY_NAME` | Idea | Main parameters |
|-----------------|------|------------------|
| `sma_cross` | Fast SMA crosses slow | `STRATEGY_FAST`, `STRATEGY_SLOW` |
| `rsi` | RSI oversold/overbought zones | `STRATEGY_RSI_PERIOD`, oversold/overbought |
| `macd` | MACD line vs signal cross | fast/slow spans + `STRATEGY_MACD_SIGNAL` |
| `bollinger` / `bb` | Price crosses outer bands | `STRATEGY_BB_PERIOD`, `STRATEGY_BB_STD` |
| `ichimoku` / `ichi` | Tenkan/Kijun cross + contemporaneous cloud filter | `STRATEGY_ICHIMOKU_*` |
| `fibonacci` / `fib` | Reclaim past a Fib retracement level in a swing | `STRATEGY_FIB_LOOKBACK`, `STRATEGY_FIB_LEVEL` |
| `volume_profile` / `vp` | Breakout vs recent POC histogram | `STRATEGY_VP_BARS`, `STRATEGY_VP_BINS` |
| `stochastic` / `stoch` | %K crosses %D from oversold/overbought zones | `STRATEGY_STOCH_K`, `STRATEGY_STOCH_D`, thresholds |
| `atr_breakout` / `atr` | Close vs prior close beyond ± `mult` × Wilder ATR | `STRATEGY_ATR_PERIOD`, `STRATEGY_ATR_MULT` |
| `ml` | Classifier on recent **log-returns** (see below) | `ML_BACKEND`, `ML_MODEL_PATH`, `STRATEGY_ML_WINDOW`, `ML_TORCH_ARCH` |

All emit **`LLMSignal`** (`action`, `size_pct`, `confidence`, `reason`) so **risk** and **execution** stay shared between modes.

### ML strategy details

- **Features:** last `STRATEGY_ML_WINDOW` closes → **log-return** vector of length `window - 1`.
- **PyTorch (`ML_BACKEND=torch`):** TorchScript model must output **3** logits/scores: **hold, long, short** (argmax → action).  
  - **`ML_TORCH_ARCH=mlp`:** input shape `[1, window-1]`.  
  - **`ML_TORCH_ARCH=lstm` or `transformer`:** input shape `[1, window-1, 1]`.
- **TensorFlow/Keras:** **flat** input `[1, window-1]` only; set `ML_TORCH_ARCH=mlp` in settings (non-MLP sequence models are **not** supported on this path).
- **Hot reload:** `ML_HOT_RELOAD` (default `true` live) and `ML_HOT_RELOAD_INTERVAL_SEC` (default `30`): each bar, if enough time passed, compare `st_mtime_ns` on `ML_MODEL_PATH` and `jit.load` / `load_model` again when the file changed (failed reload logs a warning and keeps the previous weights). **Backtests** use `ml_hot_reload=false` by default. Set `ML_HOT_RELOAD=false` to pin the initial file only.

```bash
pip install -e ".[ml-torch]"
python examples/train_ml_torch.py --arch lstm --window 32 --epochs 40 --out artifacts/ml_lstm.pt
```

**No private trade logs are required** for a first model: use **public OHLCV** from **`--fetch`** (CCXT/Binance USDM, **automatic pagination** via `endTime` when `--limit` exceeds `--page-size`) or **`--csv`**. Labels remain **automated** (next-bar return vs `eps`) — refine for production.

**Scheduled retrain (e.g. every 4 hours):** see **`examples/cron_retrain_4h.sh`**. Write the model via a temp file then **`mv`** (atomic) so mtime changes once. With **`ML_HOT_RELOAD=true`** (default), the live bot **`jit.load`s** again when **`ML_MODEL_PATH`** changes on disk; tune **`ML_HOT_RELOAD_INTERVAL_SEC`** to control how often the file is checked (default 30s).

Align **`STRATEGY_ML_WINDOW`**, **`ML_TORCH_ARCH`**, and **`ML_MODEL_PATH`** with the exported artifact before live use. Replace labels and data with your own research pipeline for real trading.

### ML training CLI flags (`examples/train_ml_torch.py`)

| Flag | Meaning |
|------|---------|
| `--fetch` | Download Binance USDM OHLCV via CCXT (public klines; no API key for read-only history). |
| `--limit` | **Total** candles to assemble (may require multiple HTTP calls). |
| `--page-size` | Max candles per request (default **1500**; exchange cap). |
| `--max-requests` | Safety cap on pagination rounds (default **500**). |
| `--csv` | Local OHLCV file (same columns as backtest CSV). |
| `--no-testnet` | Use **mainnet** public data (recommended for volume when training). |

The backtest package exposes **`fetch_ohlcv_ccxt_paginated`** in **`backtest/data.py`** if you build your own ETL.

### Periodic retrain on the server

- Use **`examples/cron_retrain_4h.sh`** (bash + env vars) or an equivalent **systemd timer** / **Kubernetes CronJob**: train → write **`${MODEL_OUT}.tmp.$$`** → **`mv -f`** onto **`ML_MODEL_PATH`**.
- With **`ML_HOT_RELOAD=true`**, the bot picks up the new file after at most one interval (**`ML_HOT_RELOAD_INTERVAL_SEC`**). Use **atomic `mv`** so mtime updates once and readers never see a half-written file.

### Real-time WebSocket klines

- Set **`USE_WEBSOCKET=true`** and install **`.[realtime]`**. Only compatible with **`SIGNAL_SOURCE=strategy`** (the bot still aligns ticks to the 1m boundary by default).
- The buffer is **REST-seeded**, then updated on **closed** (`k.x`) kline events. Reconnect uses **exponential backoff + jitter** (`WS_RECONNECT_*`).

### Telegram notifications

- If **`TELEGRAM_BOT_TOKEN`** and **`TELEGRAM_CHAT_ID`** are set, each tick sends a **formatted** message after a strategy or LLM signal is produced (before risk gating).
- **`TELEGRAM_TEMPLATE`:** `default`, `compact`, `oneline`, or `html` (use **`TELEGRAM_PARSE_MODE=HTML`** with `html`).
- **`TELEGRAM_MESSAGE_TEMPLATE`:** if non-empty, overrides named templates; use Python **`str.format`** placeholders — keys are listed in **`telegram_format.build_trade_context`** (e.g. `{symbol}`, `{action}`, `{confidence}`, `{reason}`, `{equity_usdt}`). Unknown keys become empty strings.

---

## Backtest (`futures-llm-backtest`)

```bash
futures-llm-backtest --fetch --timeframe 1h --limit 800 --strategy sma_cross --fast 10 --slow 30
futures-llm-backtest --fetch --strategy rsi --rsi-period 14 --limit 600
futures-llm-backtest --csv path/to/ohlcv.csv --strategy macd --fast 12 --slow 26 --macd-signal 9
futures-llm-backtest --fetch --strategy stoch --stoch-k 14 --stoch-d 3 --limit 600
futures-llm-backtest --fetch --strategy atr_breakout --atr-period 14 --atr-mult 1.5 --limit 800
# ML backtest requires --ml-model and optional --ml-torch-arch / --ml-backend
```

See **`futures-llm-backtest --help`** for Ichimoku, Fib, VP, and ML flags.

**CSV columns:** `timestamp_ms,open,high,low,close,volume` (header optional).

The engine is a **simplified linear-perp teaching model** (bar close fills, single fee rate). Use it for **relative** comparison and parameter exploration — validate on **out-of-sample** data and cross-check with **exchange income** when going live.

---

## Real exchange PnL (`futures-llm-real-pnl`)

Aggregates Binance USDT-M **income history** (`REALIZED_PNL`, `FUNDING_FEE`, `COMMISSION`, etc.):

```bash
futures-llm-real-pnl --days 7
futures-llm-real-pnl --since 2026-01-01 --until 2026-01-31
futures-llm-real-pnl --all-contracts --days 1
```

Transfers are shown by type but excluded from the printed “trading cashflow” subtotal. **Unrealized** PnL on open positions is **not** in this ledger — use positions / balance for a full picture.

---

## Observability & dashboard

When **`OBSERVABILITY_PORT > 0`**, a background thread serves:

- **`GET /`**, **`GET /dashboard`** — embedded HTML that polls **`/health`** every ~2.5s (ticks, orders, LLM stats, last error).  
- **`GET /health`** — JSON snapshot.  
- **`GET /metrics`** — Prometheus text exposition.

Default bind: **`127.0.0.1`**. Use SSH tunnel or reverse proxy if you access remotely.

---

## Testing

```bash
pip install -e ".[dev]"
python -m pytest tests -v
```

---

## Pinned dependencies (optional)

After a clean venv and `pip install -e ".[dev]"`, you may align versions with **[requirements-lock.txt](requirements-lock.txt)** (`-e .` lines, not absolute paths).

---

## Repository layout

| Path | Role |
|------|------|
| `src/futures_llm_bot/` | Application package (`cli`, `execution`, `backtest`, `strategy_factory`, `ml_signal_strategy`, `binance_kline_ws`, `telegram_format`, …) |
| `examples/` | **`train_ml_torch.py`** (TorchScript export; synthetic / `--csv` / paginated `--fetch`); **`cron_retrain_4h.sh`** (cron-friendly retrain → atomic `mv`) |
| `tests/` | Pytest suite |
| `ARCHITECTURE.md` | Module map, flow, extension points |
| `.env.example` | Environment template |

---

## Contributing / extensions

- **New strategies:** implement `reset` / `on_bar` → `LLMSignal`; register in **`strategy_factory`**.  
- **Alerting:** scrape `/metrics` or poll `/health`; use **Telegram** built-ins or integrate PagerDuty/Slack externally.  
- **Multi-symbol or HFT:** would require async I/O and architectural changes — not the current single-symbol sync loop.

---

## License / responsibility

No warranty. Read **[ARCHITECTURE.md](ARCHITECTURE.md)** and Binance API docs before trading real funds.
