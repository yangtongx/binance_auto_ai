# futures-llm-bot

**Languages:** [English](README.md) · [中文](README.zh.md)

**futures-llm-bot** is a Python application for **Binance USDT-M (USDⓈ-M) linear perpetual futures**. It runs a periodic loop: pull market data and account state, turn them into trade **signals**, apply **risk** and **session** limits, then place orders through **CCXT** in either **one-way** or **hedge** position mode.

You can drive signals in two ways:

1. **`SIGNAL_SOURCE=strategy`** — deterministic technical rules (same implementations as the bundled backtester): SMA cross, RSI, MACD, Bollinger bands.
2. **`SIGNAL_SOURCE=llm`** — send OHLCV plus **account context** (positions, wallet, mode) to an **OpenAI-compatible** chat API (e.g. OpenAI, DeepSeek, Azure) and parse a strict JSON signal.

The project also includes a **teaching backtest** (simplified PnL model), a **real exchange PnL** summarizer (`futures-llm-real-pnl`), optional **HTTP observability** with a small **dashboard**, and **pytest** coverage for core paths.

> **Disclaimer:** This is **experimental** software. Futures are **high risk**. Prefer **testnet** and **`DRY_RUN=true`** until you fully understand behavior. You alone are responsible for API keys, configuration, and losses. The bundled backtest is **not** a substitute for exchange-reported PnL.

---

## Features

| Area | What you get |
|------|----------------|
| **Execution** | Binance USDM via `ccxt.binanceusdm`, testnet/mainnet, one-way vs hedge handling |
| **Signals** | Rule strategies aligned with `futures-llm-backtest`, or LLM JSON output validated to `LLMSignal` |
| **Risk** | `MIN_CONFIDENCE`, notional caps (`MAX_NOTIONAL_USDT`), optional daily trade cap and daily loss cap (UTC) |
| **Session state** | JSON `STATE_FILE` with `filelock` for multi-process safety |
| **Backtest** | CSV or CCXT fetch; **close-to-close** approximation + fees (`fee_bps`); **not** full funding/leverage simulation |
| **Real PnL** | Summarize `REALIZED_PNL`, `FUNDING_FEE`, `COMMISSION` from Binance `/fapi/v1/income` |
| **Observability** | Optional `GET /`, `/dashboard`, `/health`, `/metrics` on `OBSERVABILITY_HOST:PORT` |
| **Dev UX** | Pydantic settings, `pyright` paths in `pyproject.toml`, smoke CLI flag |

---

## Architecture (short)

1. **`cli.run_loop`** waits for the next 1m boundary (unless `--once`), then executes one **tick**.
2. **Tick** fetches **USDT equity** and **positions**, optionally builds **OHLCV** and either runs **`strategy_factory`** or **`llm_decide`**.
3. **`risk.assess_signal`** filters low-confidence/size signals; **`session_risk`** may block new long/short for the UTC day.
4. **`execution`** resolves hedge mode, converts signals to orders via **`order_utils`**, and records metrics on real submissions.

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
- **Signals — rules:** `STRATEGY_NAME` (`sma_cross`, `rsi`, `macd`, `bollinger` / `bb`) and matching `STRATEGY_*` fields (see `.env.example`)  
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
- **`STRATEGY_NAME`** must match a registered id; parameters (`STRATEGY_FAST`, `STRATEGY_SLOW`, RSI/MACD/BB fields) mirror **`futures-llm-backtest --strategy ...`**.

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

All emit **`LLMSignal`** (`action`, `size_pct`, `confidence`, `reason`) so **risk** and **execution** stay shared between modes.

---

## Backtest (`futures-llm-backtest`)

```bash
futures-llm-backtest --fetch --timeframe 1h --limit 800 --strategy sma_cross --fast 10 --slow 30
futures-llm-backtest --fetch --strategy rsi --rsi-period 14 --limit 600
futures-llm-backtest --csv path/to/ohlcv.csv --strategy macd --fast 12 --slow 26 --macd-signal 9
```

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
| `src/futures_llm_bot/` | Application package (`cli`, `execution`, `backtest`, `strategy_factory`, `observability`, …) |
| `tests/` | Pytest suite |
| `ARCHITECTURE.md` | Module map, flow, extension points |
| `.env.example` | Environment template |

---

## Contributing / extensions

- **New strategies:** implement `reset` / `on_bar` → `LLMSignal`; register in **`strategy_factory`**.  
- **Alerting:** scrape `/metrics` or poll `/health`; integrate PagerDuty/Slack outside this repo.  
- **Multi-symbol or HFT:** would require async I/O and architectural changes — not the current single-symbol sync loop.

---

## License / responsibility

No warranty. Read **[ARCHITECTURE.md](ARCHITECTURE.md)** and Binance API docs before trading real funds.
