# binance_auto_ai

**Languages:** [English](README.md) · [中文](README.zh.md)


**binance_auto_ai** is a Python application for **Binance USDT-M (USDⓈ-M) linear perpetual futures**. It runs a periodic loop: pull market data and account state, turn them into trade **signals**, apply **risk** and **session** limits, then place orders through **CCXT** in either **one-way** or **hedge** position mode.

You can drive signals in two ways:

1. **`SIGNAL_SOURCE=strategy`** — deterministic technical rules (same implementations as the bundled backtester): SMA cross, RSI, **rsi_adaptive**, MACD, Bollinger, Ichimoku-style cloud, Fibonacci pullback reclaim, volume-profile POC breakout, **Stochastic**, **ATR breakout**, optional **ML** (TorchScript / Keras), **composite** ensembles, optional **RL** (**Stable-Baselines3**).
2. **`SIGNAL_SOURCE=llm`** — send OHLCV plus **account context** (positions, wallet, mode) to an **OpenAI-compatible** chat API (e.g. OpenAI, DeepSeek, Azure) and parse a strict JSON signal.

The project also includes a **teaching backtest** (simplified PnL model), a **real exchange PnL** summarizer (`binance-auto-real-pnl`), a **rolling VaR** diagnostics command (`binance-auto-var-validate`), optional **HTTP observability** with a small **dashboard**, and **pytest** coverage for core paths.

> **Disclaimer:** This is **experimental** software. Futures are **high risk**. Prefer **testnet** and **`DRY_RUN=true`** until you fully understand behavior. You alone are responsible for API keys, configuration, and losses. The bundled backtest is **not** a substitute for exchange-reported PnL.

---

## Features

| Area | What you get |
|------|----------------|
| **Execution** | Binance USDM via `ccxt.binanceusdm`, testnet/mainnet, one-way vs hedge handling |
| **Signals** | Rule strategies aligned with `binance-auto-backtest`, or LLM JSON output validated to `LLMSignal` |
| **Live WS (optional)** | `USE_WEBSOCKET=true`: REST-seeded + Binance **closed** kline stream, exponential backoff reconnect (`WS_RECONNECT_*`) |
| **Telegram (optional)** | Named templates or custom `TELEGRAM_MESSAGE_TEMPLATE`; JSON `sendMessage` + optional `TELEGRAM_PARSE_MODE` |
| **ML (optional)** | `STRATEGY_NAME=ml`: TorchScript (`ML_TORCH_ARCH=mlp\|lstm\|transformer`) or Keras flat MLP; **`ML_HOT_RELOAD`** watches `ML_MODEL_PATH` mtime (throttled) |
| **ML training / ops** | `examples/train_ml_torch.py` (CSV / **paginated `--fetch`**); **`examples/cron_retrain_4h.sh`** for periodic retrain + atomic replace |
| **Advanced rules** | **`composite`** (ensemble voting), **`rsi_adaptive`** (volatility-scaled RSI bands), **`rl_sb3`** (Stable-Baselines3 policy; **`.[rl]`**) |
| **RL training** | `examples/train_rl_sb3.py`: **Gymnasium** `FuturesPerpBarEnv`, reward modes (`pnl` / `pnl_cost` / `risk_adjusted`), PPO + tunable hyperparameters |
| **VaR validation** | **`binance-auto-var-validate`**: rolling historical VaR vs realized log returns, **Kupiec** coverage statistic (CLI on `--csv` or `--fetch`) |
| **Risk** | `MIN_CONFIDENCE`, notional caps (`MAX_NOTIONAL_USDT`), optional daily trade cap and daily loss cap (UTC); optional **`RISK_VAR_*`** gate + **`RISK_CORR_*`** logging in **`cli`** |
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
| `dev` | `pip install -e ".[dev]"` | `pytest` + **gymnasium** (env smoke tests) |
| `realtime` | `pip install -e ".[realtime]"` | `websocket-client` for **`USE_WEBSOCKET`** |
| `ml-torch` | `pip install -e ".[ml-torch]"` | PyTorch for **TorchScript** ML inference + **training example** |
| `ml-tf` | `pip install -e ".[ml-tf]"` | TensorFlow/Keras for **flat** ML models only |
| `rl` | `pip install -e ".[rl]"` | **stable-baselines3** + **gymnasium** for **`rl_sb3`** and **`train_rl_sb3.py`** |

Editable install exposes console scripts:

| Command | Purpose |
|---------|---------|
| `binance-auto-ai` | Main trading loop |
| `binance-auto-backtest` | Rule backtest on CSV or `--fetch` |
| `binance-auto-real-pnl` | Binance income history summary |
| `binance-auto-var-validate` | Rolling **VaR backtest** + Kupiec statistic on historical log returns |

Without `pip install -e .`, set **`PYTHONPATH=src`** before `python -m binance_auto_ai`.

---

## Docker (Tencent CNB / Kubernetes / container hosts)

The repo includes a **`Dockerfile`**. **Do not** put API keys in the image or Git: configure **`BINANCE_API_KEY`**, **`BINANCE_API_SECRET`**, **`OPENAI_API_KEY`**, **`OPENAI_BASE_URL`**, **`OPENAI_MODEL`**, and the rest as **runtime environment variables** (CNB/K8s secrets, platform “环境变量”, etc.).

```bash
docker build -t binance-auto-ai:local .
docker run --rm \
  -e BINANCE_API_KEY -e BINANCE_API_SECRET \
  -e OPENAI_API_KEY -e OPENAI_BASE_URL=https://api.deepseek.com -e OPENAI_MODEL=deepseek-v4-pro \
  -e SIGNAL_SOURCE=llm -e BINANCE_TESTNET=true -e DRY_RUN=true \
  -v bot-state:/data \
  binance-auto-ai:local
```

Volume **`/data`** persists session risk state (`STATE_FILE` defaults to `/data/.binance_auto_ai_state.json` in the image). Use **`binance-auto-real-pnl`** / **`binance-auto-backtest`** in CI or a sidecar only if you add those to the image (`pip install` already includes entry points).

On **[Gitee](https://gitee.com)**: **https://gitee.com/yang-huidong/binance_auto_ai** — build from this `Dockerfile`; **never** commit `.env` or keys.

**Recommended server path:** `/opt/binance_auto_ai`

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
- **Composite (optional):** when **`STRATEGY_NAME=composite`** — `COMPOSITE_MEMBERS` (comma-separated leaf ids), **`COMPOSITE_MODE`** (`majority` \| `weighted` \| `unanimous` \| `first`), optional **`COMPOSITE_WEIGHTS`**  
- **Vol-adaptive RSI (optional):** when **`STRATEGY_NAME=rsi_adaptive`** — `STRATEGY_VOL_WINDOW`, `STRATEGY_VOL_REF_WINDOW`, `STRATEGY_VOL_SENSITIVITY` (plus base `STRATEGY_RSI_*`)  
- **RL (optional):** when **`STRATEGY_NAME=rl_sb3`** — **`RL_MODEL_PATH`** (SB3 zip), **`RL_WINDOW`**; requires **`.[rl]`**  
- **Risk analytics (optional):** `RISK_VAR_WINDOW`, `RISK_VAR_ALPHA`, **`RISK_VAR_BLOCK`**, `RISK_VAR_TAIL_LIMIT` (empirical return VaR gate on directional signals); **`RISK_CORR_AUX_SYMBOL`**, **`RISK_CORR_LOG_EVERY`** (log-return correlation vs `SYMBOL`)  
- **Position / HTTP:** `POSITION_MODE`, `EXCHANGE_TIMEOUT_MS`, `POSITION_POLL_*`  
- **Session risk:** `MAX_TRADES_PER_DAY`, `MAX_DAILY_LOSS_USDT`, `STATE_FILE`, `DAILY_LOSS_WARN_RATIO`  
- **Observability:** `OBSERVABILITY_HOST`, `OBSERVABILITY_PORT` (non-zero enables HTTP UI + JSON + Prometheus text)

`FLAT` / `HOLD` are **not** blocked by daily trade or loss limits so you can still reduce risk.

---

## Running the bot

```bash
binance-auto-ai              # loop (waits for candle boundary)
binance-auto-ai --once       # single tick, then exit
binance-auto-ai --smoke      # load settings + imports only; no API calls
```

As a module:

```bash
python -m binance_auto_ai --once
```

---

## Signal sources

### Rule mode (`SIGNAL_SOURCE=strategy`, default in `.env.example`)

- Uses **`strategy_factory.build_live_strategy`** — same strategy classes as the backtester.  
- **`OPENAI_API_KEY`** is **not** required.  
- **`STRATEGY_NAME`** must match a registered id; parameters mirror **`binance-auto-backtest`** (including **composite**, **rsi_adaptive**, **rl_sb3** — see **[Strategies](#strategies-rules)**).

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
| `rsi_adaptive` | RSI bands widen/tighten from rolling realized vol | `STRATEGY_RSI_*`, `STRATEGY_VOL_WINDOW`, `STRATEGY_VOL_REF_WINDOW`, `STRATEGY_VOL_SENSITIVITY` |
| `macd` | MACD line vs signal cross | fast/slow spans + `STRATEGY_MACD_SIGNAL` |
| `bollinger` / `bb` | Price crosses outer bands | `STRATEGY_BB_PERIOD`, `STRATEGY_BB_STD` |
| `ichimoku` / `ichi` | Tenkan/Kijun cross + contemporaneous cloud filter | `STRATEGY_ICHIMOKU_*` |
| `fibonacci` / `fib` | Reclaim past a Fib retracement level in a swing | `STRATEGY_FIB_LOOKBACK`, `STRATEGY_FIB_LEVEL` |
| `volume_profile` / `vp` | Breakout vs recent POC histogram | `STRATEGY_VP_BARS`, `STRATEGY_VP_BINS` |
| `stochastic` / `stoch` | %K crosses %D from oversold/overbought zones | `STRATEGY_STOCH_K`, `STRATEGY_STOCH_D`, thresholds |
| `atr_breakout` / `atr` | Close vs prior close beyond ± `mult` × Wilder ATR | `STRATEGY_ATR_PERIOD`, `STRATEGY_ATR_MULT` |
| `ml` | Classifier on recent **log-returns** (see below) | `ML_BACKEND`, `ML_MODEL_PATH`, `STRATEGY_ML_WINDOW`, `ML_TORCH_ARCH` |
| `composite` | Runs multiple **leaf** strategies each bar; merges signals (see **`.env.example`**) | `COMPOSITE_MEMBERS`, `COMPOSITE_MODE`, optional `COMPOSITE_WEIGHTS`; children share the same param bundle |
| `rl_sb3` | **PPO** (or other SB3) policy on clipped log-return window → discrete hold/long/short | **`RL_MODEL_PATH`**, **`RL_WINDOW`** (requires **`.[rl]`**); train with **`examples/train_rl_sb3.py`** |

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

### RL strategy (`rl_sb3`) and training

- **Live / backtest:** **`STRATEGY_NAME=rl_sb3`** loads a **Stable-Baselines3** checkpoint (**`RL_MODEL_PATH`**, zip from `model.save`). Observation matches training: **`RL_WINDOW`** closes → **`RL_WINDOW-1`** clipped **log-returns**; actions **0 / 1 / 2** = **flat / long / short** (target net position for the **next** bar’s log return).
- **Install:** `pip install -e ".[rl]"` (pulls **gymnasium** + **stable-baselines3**).
- **Environment:** `binance_auto_ai.rl.futures_perp_env.FuturesPerpBarEnv` — reward modes **`pnl`**, **`pnl_cost`** (turnover × `trans_cost`), **`risk_adjusted`** (drawdown penalty on a simple cumulative PnL trace).

```bash
pip install -e ".[rl]"
python examples/train_rl_sb3.py --fetch --no-testnet --symbol BTC/USDT:USDT --timeframe 1h \
  --limit 8000 --window 48 --timesteps 200000 --reward pnl_cost --out artifacts/rl_ppo.zip
```

| `train_rl_sb3.py` (subset) | Meaning |
|----------------------------|---------|
| `--timesteps` | PPO **`total_timesteps`** |
| `--learning-rate`, `--n-steps`, `--batch-size` | PPO optimizer / rollout |
| `--gamma`, `--gae-lambda`, `--clip-range`, `--ent-coef` | PPO stability / exploration |
| `--net-arch` | MLP widths, e.g. `64,64` |
| `--episode-len` | Steps per Gymnasium episode |
| `--reward`, `--trans-cost`, `--drawdown-penalty` | Reward shaping |

Align **`RL_WINDOW`** and the saved zip path with **`RL_MODEL_PATH`** before live use. Training rewards are **simplified** (bar log returns, not fees/funding); refine for production.

### VaR backtest CLI (`binance-auto-var-validate`)

Offline check of **rolling historical VaR** on **log returns**: at each `t`, VaR = `alpha` quantile of the prior **`lookback`** returns; a **violation** occurs if the **realized** return at `t` is **below** that VaR. The tool reports the **empirical hit rate** and a **Kupiec** unconditional coverage likelihood-ratio statistic (~ χ²(1); flag **`reject_h0_coverage_5pct`** vs critical value **3.84**).

```bash
binance-auto-var-validate --fetch --no-testnet --symbol BTC/USDT:USDT --timeframe 1h --limit 5000 --lookback 250 --alpha 0.05
binance-auto-var-validate --csv data/btc.csv --lookback 250 --alpha 0.05 --json-out var_report.json
```

**Caveats:** i.i.d. returns are assumed in the simplest interpretation; **volatility clustering** breaks independence — consider **Christoffersen** / independence tests or **filtered historical simulation** for regulatory-grade work. The **live** **`RISK_VAR_*`** gate in **`cli`** uses the same quantile idea on the trailing **`RISK_VAR_WINDOW`** window.

### Real-time WebSocket klines

- Set **`USE_WEBSOCKET=true`** and install **`.[realtime]`**. Only compatible with **`SIGNAL_SOURCE=strategy`** (the bot still aligns ticks to the 1m boundary by default).
- The buffer is **REST-seeded**, then updated on **closed** (`k.x`) kline events. Reconnect uses **exponential backoff + jitter** (`WS_RECONNECT_*`).

### Telegram notifications

- If **`TELEGRAM_BOT_TOKEN`** and **`TELEGRAM_CHAT_ID`** are set, each tick sends a **formatted** message after a strategy or LLM signal is produced (before risk gating).
- **`TELEGRAM_TEMPLATE`:** `default`, `compact`, `oneline`, or `html` (use **`TELEGRAM_PARSE_MODE=HTML`** with `html`).
- **`TELEGRAM_MESSAGE_TEMPLATE`:** if non-empty, overrides named templates; use Python **`str.format`** placeholders — keys are listed in **`telegram_format.build_trade_context`** (e.g. `{symbol}`, `{action}`, `{confidence}`, `{reason}`, `{equity_usdt}`). Unknown keys become empty strings.

---

## Backtest (`binance-auto-backtest`)

```bash
binance-auto-backtest --fetch --timeframe 1h --limit 800 --strategy sma_cross --fast 10 --slow 30
binance-auto-backtest --fetch --strategy rsi --rsi-period 14 --limit 600
binance-auto-backtest --csv path/to/ohlcv.csv --strategy macd --fast 12 --slow 26 --macd-signal 9
binance-auto-backtest --fetch --strategy stoch --stoch-k 14 --stoch-d 3 --limit 600
binance-auto-backtest --fetch --strategy atr_breakout --atr-period 14 --atr-mult 1.5 --limit 800
# ML backtest requires --ml-model and optional --ml-torch-arch / --ml-backend
```

See **`binance-auto-backtest --help`** for Ichimoku, Fib, VP, **composite** (`--composite-members`, …), **rsi_adaptive** (`--vol-*`), **ML**, and **rl_sb3** (`--rl-model`, **`.[rl]`** required to run).

For **VaR calibration** on the same history, use **`binance-auto-var-validate`** (rolling quantile backtest + Kupiec).

**CSV columns:** `timestamp_ms,open,high,low,close,volume` (header optional).

The engine is a **simplified linear-perp teaching model** (bar close fills, single fee rate). Use it for **relative** comparison and parameter exploration — validate on **out-of-sample** data and cross-check with **exchange income** when going live.

---

## Real exchange PnL (`binance-auto-real-pnl`)

Aggregates Binance USDT-M **income history** (`REALIZED_PNL`, `FUNDING_FEE`, `COMMISSION`, etc.):

```bash
binance-auto-real-pnl --days 7
binance-auto-real-pnl --since 2026-01-01 --until 2026-01-31
binance-auto-real-pnl --all-contracts --days 1
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
| `src/binance_auto_ai/` | Application package (`cli`, `execution`, `backtest`, `strategy_factory`, `ml_signal_strategy`, `rl/`, `risk_metrics`, `var_validation` …) |
| `examples/` | **`train_ml_torch.py`**, **`train_rl_sb3.py`** (SB3 PPO); **`cron_retrain_4h.sh`** (atomic `mv` retrain) |
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
