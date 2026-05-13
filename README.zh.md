# futures-llm-bot

**语言:** [English](README.md) · [中文](README.zh.md)

**futures-llm-bot** 是一个面向 **币安 USDT-M（USDⓈ-M / U 本位）线性永续合约** 的 Python 程序。它在固定周期内：**拉行情与账户状态 → 生成交易信号 → 经过风控与会话限制 → 通过 CCXT 下单**，支持 **单向持仓（one-way）** 与 **双向持仓（hedge）** 两种模式。

信号有两种来源：

1. **`SIGNAL_SOURCE=strategy`（默认）** — 使用与内置回测 **完全一致** 的规则类：均线交叉、RSI、MACD、布林带、**一目均衡表（简化云带）**、**斐波那契回撤收回**、**成交量分布 POC 突破**、**随机指标**、**ATR 突破**，以及可选 **机器学习**（TorchScript / Keras）。
2. **`SIGNAL_SOURCE=llm`** — 将 **OHLCV** 与 **账户上下文**（持仓、钱包、持仓模式等）发给 **OpenAI 兼容** 的 Chat API（如 OpenAI、DeepSeek、Azure），解析严格 **JSON** 为交易信号。

仓库还包含：**教学向简化回测**、基于交易所流水的 **真实盈亏汇总 CLI**（`futures-llm-real-pnl`）、可选的 **HTTP 可观测性** 与 **简易仪表盘**，以及核心路径的 **pytest** 测试。

> **免责声明：** 本项目为 **实验性** 软件，**合约交易风险极高**。请在充分理解行为前优先使用 **测试网** 与 **`DRY_RUN=true`**。API Key、配置与亏损由使用者自行承担。**内置回测的 PnL 为简化模型，不能替代交易所账单级真实盈亏。**

---

## 功能一览

| 模块 | 说明 |
|------|------|
| **下单执行** | `ccxt.binanceusdm`；支持测试网/主网；单向与双向持仓分支逻辑 |
| **信号** | 与 `futures-llm-backtest` 对齐的规则策略，或 LLM 输出的 `LLMSignal` |
| **实时 WS（可选）** | `USE_WEBSOCKET=true`：REST 预热 + 币安 **已收盘** K 线流，断线重连为 **指数退避 + 抖动**（`WS_RECONNECT_*`） |
| **Telegram（可选）** | 内置模板或自定义 `TELEGRAM_MESSAGE_TEMPLATE`；JSON `sendMessage`；可选 `TELEGRAM_PARSE_MODE` |
| **ML（可选）** | `STRATEGY_NAME=ml`：TorchScript（`ML_TORCH_ARCH=mlp\|lstm\|transformer`）或 Keras 扁平 MLP；**`ML_HOT_RELOAD`** 按间隔检查 `ML_MODEL_PATH` 的 **mtime** 并热加载 |
| **ML 训练 / 运维** | `examples/train_ml_torch.py`（`--csv` / **分页 `--fetch`**）；**`examples/cron_retrain_4h.sh`** 定时重训 + **原子 `mv` 替换** |
| **风控** | `MIN_CONFIDENCE`、名义上限 `MAX_NOTIONAL_USDT`、可选 UTC 自然日 **日交易次数 / 日亏损** 限制 |
| **会话状态** | JSON `STATE_FILE`，跨进程用 `filelock` |
| **回测** | CSV 或 CCXT 拉取；按 Bar **收盘价** 近似成交 + `fee_bps`；**不含** 完整资金费/保证金/强平等仿真 |
| **真实 PnL** | 拉取 `/fapi/v1/income` 汇总已实现盈亏、资金费、手续费等 |
| **可观测性** | 可选 `GET /`、`/dashboard`、`/health`、`/metrics` |
| **开发体验** | Pydantic 配置、`pyproject.toml` 中 Pyright 路径、`--smoke` 自检 |

---

## 架构（简述）

1. **`cli.run_loop`** 在默认 **1 分钟** 周期边界触发（`--once` 则只跑一轮）。
2. **Tick** 读取 **USDT 权益**、**持仓**。**K 线** 默认 `fetch_ohlcv`；若 **`USE_WEBSOCKET=true`**（仅 **strategy** 模式），则使用线程安全的 **`BinanceUsdMKlineBuffer`**（仅处理 **已收盘** K 线）；长度不足时可回落 REST。
3. 产生信号后，若配置了 **Telegram**，**`telegram_notify`** 会发送 **模板化** 消息（在风控闸门之前）。
4. **`risk.assess_signal`** 过滤信号；**`session_risk`** 可按 UTC 日限制新开多/空。
5. **`execution`** 解析持仓模式，经 **`order_utils`** 下单，真实报单可记 **metrics**。

更细的流程图与模块表见 **[ARCHITECTURE.md](ARCHITECTURE.md)**（英文）。

---

## 环境要求

- **Python** ≥ 3.10  
- 若 **`DRY_RUN=false`**：需具备 **U 本位合约** 权限的 **币安 API**（密钥上勿开启 **提币**）  
- 仅当 **`SIGNAL_SOURCE=llm`** 时需要 **`OPENAI_API_KEY`**

---

## 安装

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -e ".[dev]"
copy .env.example .env   # Windows；Unix 用 cp
```

**可选依赖组**（按需安装）：

| 额外配置 | 安装命令 | 用途 |
|----------|----------|------|
| （默认） | `pip install -e .` | 核心机器人 + 回测 |
| `dev` | `pip install -e ".[dev]"` | `pytest` |
| `realtime` | `pip install -e ".[realtime]"` | `websocket-client`，启用 **`USE_WEBSOCKET`** |
| `ml-torch` | `pip install -e ".[ml-torch]"` | PyTorch：**TorchScript 推理** + **训练示例** |
| `ml-tf` | `pip install -e ".[ml-tf]"` | TensorFlow/Keras：**仅扁平** MLP 推理 |

安装后可使用入口命令：

| 命令 | 作用 |
|------|------|
| `futures-llm-bot` | 主交易循环 |
| `futures-llm-backtest` | 规则回测（CSV 或 `--fetch`） |
| `futures-llm-real-pnl` | 币安 USDT-M **收入 / income** 汇总 |

若未执行 `pip install -e .`，可设置 **`PYTHONPATH=src`** 后使用 `python -m futures_llm_bot`。

---

## Docker（腾讯云 CNB / K8s / 容器）

仓库根目录提供 **`Dockerfile`**。**禁止**把密钥写进镜像或 Git：在 **运行时环境变量** 或平台「密钥 / Secret」中配置 **`BINANCE_API_KEY`**、**`BINANCE_API_SECRET`**、**`OPENAI_API_KEY`**、**`OPENAI_BASE_URL`**、**`OPENAI_MODEL`** 等（与 `.env.example` 同名即可）。

```bash
docker build -t futures-llm-bot:local .
docker run --rm \
  -e BINANCE_API_KEY -e BINANCE_API_SECRET \
  -e OPENAI_API_KEY -e OPENAI_BASE_URL=https://api.deepseek.com -e OPENAI_MODEL=deepseek-v4-pro \
  -e SIGNAL_SOURCE=llm -e BINANCE_TESTNET=true -e DRY_RUN=true \
  -v bot-state:/data \
  futures-llm-bot:local
```

**`/data`** 卷用于持久化 **`STATE_FILE`**（镜像内默认为 `/data/.futures_llm_bot_state.json`）。

在 **[cnb.cool](https://cnb.cool)**：绑定仓库 **https://cnb.cool/xiaoYang-2026/futures_llm_bot** ，构建指向本 `Dockerfile`，镜像推送到你的仓库后，在运行环境中注入上述变量；**切勿**把 `.env` 或真实 Key 提交到代码库。

---

## 配置说明

将 **`.env.example`** 复制为 **`.env`**（从仓库根目录加载）。主要分组：

- **币安：** `BINANCE_API_KEY`、`BINANCE_API_SECRET`、`BINANCE_TESTNET`  
- **LLM（`SIGNAL_SOURCE=llm`）：** `OPENAI_API_KEY`、可选 `OPENAI_BASE_URL`、`OPENAI_MODEL`、超时与重试  
- **交易：** `SYMBOL`（如 `BTC/USDT:USDT`）、`TIMEFRAME`、`KLINES_LIMIT`、`MAX_NOTIONAL_USDT`、`DRY_RUN`、`MIN_CONFIDENCE`  
- **规则信号：** `STRATEGY_NAME` 及 Ichimoku / Fib / VP / Stoch / ATR / ML 等 **`STRATEGY_*`（见下文 [内置规则策略](#内置规则策略) 与 `.env.example`）**  
- **WebSocket（可选）：** `USE_WEBSOCKET`、`WS_RECONNECT_*`（需 `.[realtime]`；**仅 strategy 模式**）  
- **Telegram（可选）：** `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`TELEGRAM_TEMPLATE`、`TELEGRAM_MESSAGE_TEMPLATE`、`TELEGRAM_PARSE_MODE`  
- **ML（可选）：** `ML_BACKEND`、`ML_MODEL_PATH`、`STRATEGY_ML_WINDOW`、`ML_TORCH_ARCH`；**`ML_HOT_RELOAD`**（默认 `true`）、**`ML_HOT_RELOAD_INTERVAL_SEC`**（默认 `30`，`STRATEGY_NAME=ml` 时两次 mtime 检查的最小间隔秒数）  
- **持仓 / HTTP：** `POSITION_MODE`、`EXCHANGE_TIMEOUT_MS`、`POSITION_POLL_*`  
- **会话风控：** `MAX_TRADES_PER_DAY`、`MAX_DAILY_LOSS_USDT`、`STATE_FILE`、`DAILY_LOSS_WARN_RATIO`  
- **可观测性：** `OBSERVABILITY_HOST`、`OBSERVABILITY_PORT`（非 0 则启用内置页面与 JSON/Prometheus）

**`FLAT` / `HOLD`** 不受日交易笔数、日亏损上限阻挡，便于减仓或平仓。

---

## 运行机器人

```bash
futures-llm-bot              # 循环（等待 K 线闭合）
futures-llm-bot --once       # 单次 tick 后退出
futures-llm-bot --smoke      # 仅加载配置与 import，不调交易所与 OpenAI
```

模块方式：

```bash
python -m futures_llm_bot --once
```

---

## 信号源说明

### 规则模式（`SIGNAL_SOURCE=strategy`）

- 使用 **`strategy_factory.build_live_strategy`**，与 **`futures-llm-backtest --strategy`** 为同一套类。  
- **不需要** `OPENAI_API_KEY`。  
- **`STRATEGY_NAME`** 须为已注册 id；参数与 **`futures-llm-backtest`** 一致（均线/RSI/MACD/BB/一目/Fib/VP/随机/ATR/ML，见 **[内置规则策略](#内置规则策略)**）。

### LLM 模式（`SIGNAL_SOURCE=llm`）

- 拼装 **最近 K 线表格 + 账户上下文** 文本。  
- **`llm_strategy.llm_decide`** 带重试；输出校验为 **`LLMSignal`**。  
- 通过 `OPENAI_BASE_URL` 可接 **DeepSeek** 等兼容端点。

---

## 内置规则策略

| `STRATEGY_NAME` | 思路 | 主要参数 |
|-----------------|------|----------|
| `sma_cross` | 快/慢均线交叉 | `STRATEGY_FAST`、`STRATEGY_SLOW` |
| `rsi` | RSI 超卖/超买区 | `STRATEGY_RSI_PERIOD`、超买超卖阈值 |
| `macd` | MACD 线与信号线交叉 | 快慢周期 + `STRATEGY_MACD_SIGNAL` |
| `bollinger` / `bb` | 价格穿上下轨 | `STRATEGY_BB_PERIOD`、`STRATEGY_BB_STD` |
| `ichimoku` / `ichi` | 转换/基准线交叉 + **同期**云带过滤 | `STRATEGY_ICHIMOKU_*` |
| `fibonacci` / `fib` | 摆动 leg 中斐波位 **收回** | `STRATEGY_FIB_LOOKBACK`、`STRATEGY_FIB_LEVEL` |
| `volume_profile` / `vp` | 相对 POC 突破 | `STRATEGY_VP_BARS`、`STRATEGY_VP_BINS` |
| `stochastic` / `stoch` | 超卖/超买区 %K 与 %D 交叉 | `STRATEGY_STOCH_*` |
| `atr_breakout` / `atr` | 收盘相对昨收突破 ± `mult×ATR` | `STRATEGY_ATR_PERIOD`、`STRATEGY_ATR_MULT` |
| `ml` | 最近 **对数收益** 序列上的分类器 | `ML_BACKEND`、`ML_MODEL_PATH`、`STRATEGY_ML_WINDOW`、`ML_TORCH_ARCH` |

统一输出 **`LLMSignal`**，**风控与执行** 在 LLM 与规则之间复用。

### ML 策略说明

- **特征：** 最近 `STRATEGY_ML_WINDOW` 根收盘 → 长度 `window-1` 的 **对数收益** 向量。
- **PyTorch：** TorchScript 模型须输出 **3** 维分数：**hold / long / short**（argmax）。`ML_TORCH_ARCH=mlp` 时输入 `[1, window-1]`；`lstm` / `transformer` 时输入 `[1, window-1, 1]`。
- **TensorFlow/Keras：** 仅支持 **扁平** `[1, window-1]`；序列模型请走 PyTorch。
- **热加载：** `ML_HOT_RELOAD`（实盘默认 `true`）、`ML_HOT_RELOAD_INTERVAL_SEC`（默认 `30`）：按间隔检查 `ML_MODEL_PATH` 的 **mtime**，变化则重新 `jit.load` / `load_model`；加载失败会打日志并沿用旧权重。**回测**默认关闭热加载。设为 `false` 可固定启动时那一份模型。
- **训练示例**（合成数据，仅供演示）：

```bash
pip install -e ".[ml-torch]"
python examples/train_ml_torch.py --arch lstm --window 32 --epochs 40 --out artifacts/ml_lstm.pt
# 公网 K 线：``--limit`` 大于单次上限时会 **自动分页**（``--page-size``，默认 1500）
python examples/train_ml_torch.py --fetch --no-testnet --symbol BTC/USDT:USDT --timeframe 4h --limit 20000 \\
  --page-size 1500 --arch lstm --window 48 --out artifacts/ml_latest.pt
```

**定时重训（例如每 4 小时）：** 见 **`examples/cron_retrain_4h.sh`** 与下文 **[服务器上定时重训](#服务器上定时重训)**。写入模型时使用临时文件再 **`mv`**（原子替换），`mtime` 只跳变一次；**`ML_HOT_RELOAD=true`**（默认）时实盘进程会按 **`ML_HOT_RELOAD_INTERVAL_SEC`**（默认 30 秒）检测并 **`jit.load` / `load_model`**，一般 **无需重启**。

**不需要**你自己的成交明细也能先跑通：用 **`--fetch`**（CCXT / 币安 USDM 公网 K 线；当 **`--limit`** 大于 **`--page-size`** 时按 **`endTime` 自动分页**）或 **`--csv`**（与回测相同列）。示例里的标签仍是 **自动化启发式**（下一根 K 对数收益相对 `eps`），**不等于**可盈利的真实标签，实盘前请自行设计标签与特征。

实盘前请自行替换 **标签与数据管道**；并保证 **`STRATEGY_ML_WINDOW`、`ML_TORCH_ARCH`、`ML_MODEL_PATH`** 与导出模型一致。

### ML 训练 CLI 参数（`examples/train_ml_torch.py`）

| 参数 | 含义 |
|------|------|
| `--fetch` | 通过 CCXT 下载币安 USDM OHLCV（公网 K 线；只读历史无需 API Key）。 |
| `--limit` | 需要组装的 **总** K 线根数（可能多轮 HTTP）。 |
| `--page-size` | 单次请求上限（默认 **1500**；交易所 cap）。 |
| `--max-requests` | 分页轮次安全上限（默认 **500**）。 |
| `--csv` | 本地 OHLCV 文件（列与回测 CSV 相同）。 |
| `--no-testnet` | 使用 **主网** 公网数据（训练时通常量更大）。 |

回测子包在 **`backtest/data.py`** 中提供 **`fetch_ohlcv_ccxt_paginated`**，便于自建 ETL。

### 服务器上定时重训

- 使用 **`examples/cron_retrain_4h.sh`**（bash + 环境变量）或等效的 **systemd timer** / **Kubernetes CronJob**：训练 → 写入 **`${MODEL_OUT}.tmp.$$`** → **`mv -f`** 覆盖 **`ML_MODEL_PATH`**。
- **`ML_HOT_RELOAD=true`** 时，进程最多每隔 **`ML_HOT_RELOAD_INTERVAL_SEC`** 检查一次磁盘；请始终用 **原子 `mv`**，避免读到半截文件并保证 mtime 一次更新。

### WebSocket 实时 K 线

- 设置 **`USE_WEBSOCKET=true`** 并安装 **`.[realtime]`**；仅 **`SIGNAL_SOURCE=strategy`**。主循环仍默认在 1m 边界附近醒来。
- 缓冲：**REST 预热** + 仅处理 **已收盘**（`k.x`）推送；断线后 **指数退避 + 抖动** 重连（`WS_RECONNECT_*`）。

### Telegram 通知

- 配置 **`TELEGRAM_BOT_TOKEN`** 与 **`TELEGRAM_CHAT_ID`** 后，每个 **tick** 在产出规则或 LLM 信号后会发一条 **模板消息**（在风控拦截之前）。
- **`TELEGRAM_TEMPLATE`：** `default`、`compact`、`oneline`、`html`（`html` 建议配合 **`TELEGRAM_PARSE_MODE=HTML`**）。
- **`TELEGRAM_MESSAGE_TEMPLATE`：** 非空则覆盖内置模板；占位符为 Python **`format`** 语法，可用键见代码 **`telegram_format.build_trade_context`**；未提供的键置空。

---

## 回测（`futures-llm-backtest`）

```bash
futures-llm-backtest --fetch --timeframe 1h --limit 800 --strategy sma_cross --fast 10 --slow 30
futures-llm-backtest --fetch --strategy rsi --rsi-period 14 --limit 600
futures-llm-backtest --csv path/to/ohlcv.csv --strategy macd --fast 12 --slow 26 --macd-signal 9
futures-llm-backtest --fetch --strategy stoch --stoch-k 14 --stoch-d 3 --limit 600
futures-llm-backtest --fetch --strategy atr_breakout --atr-period 14 --atr-mult 1.5 --limit 800
# ML 回测需指定 --ml-model，可选 --ml-torch-arch / --ml-backend
```

**`futures-llm-backtest --help`** 可查看一目、Fib、VP、ML 等参数。

**CSV 列：** `timestamp_ms,open,high,low,close,volume`（可有可无表头）。

引擎为 **教学向简化线性永续近似**（收盘价成交、单一费率等），适合 **参数对比与初筛**；实盘前请做 **样本外** 验证，并用 **`futures-llm-real-pnl`** 对照交易所流水。

---

## 真实盈亏（`futures-llm-real-pnl`）

汇总币安 USDT-M **收入历史**（已实现盈亏、资金费、手续费等）：

```bash
futures-llm-real-pnl --days 7
futures-llm-real-pnl --since 2026-01-01 --until 2026-01-31
futures-llm-real-pnl --all-contracts --days 1
```

划转等类型会单独展示；**未实现盈亏** 不在 income 流水中体现，需结合 **持仓/权益** 查看。

---

## 可观测性与仪表盘

当 **`OBSERVABILITY_PORT > 0`** 时，后台线程提供：

- **`GET /`**、**`GET /dashboard`** — 内嵌 HTML，轮询 **`/health`**，展示 tick、报单、LLM 统计、最近错误等。  
- **`GET /health`** — JSON。  
- **`GET /metrics`** — Prometheus 文本格式。

默认监听 **`127.0.0.1`**；远程访问请用 **SSH 隧道或反向代理**。

---

## 测试

```bash
pip install -e ".[dev]"
python -m pytest tests -v
```

---

## 依赖锁定（可选）

在干净虚拟环境中 `pip install -e ".[dev]"` 后，可用 **[requirements-lock.txt](requirements-lock.txt)** 对齐传递依赖（其中为 `-e .`，无绝对路径）。

---

## 目录结构

| 路径 | 说明 |
|------|------|
| `src/futures_llm_bot/` | 主包（`cli`、`execution`、`backtest`、`strategy_factory`、`ml_signal_strategy`、`binance_kline_ws`、`telegram_format` 等） |
| `examples/` | **`train_ml_torch.py`**（TorchScript 导出；合成 / `--csv` / 分页 `--fetch`）；**`cron_retrain_4h.sh`**（适合 cron 的重训 → 原子 `mv`） |
| `tests/` | Pytest |
| `ARCHITECTURE.md` | 模块与数据流（英文） |
| `.env.example` | 环境变量模板 |

---

## 扩展与后续方向

- **新策略：** 实现 `reset` / `on_bar` → `LLMSignal`，在 **`strategy_factory`** 注册。  
- **告警：** 外部抓取 **`/metrics`** 或轮询 **`/health`**；或使用内置 **Telegram**，亦可对接 PagerDuty / Slack。  
- **多品种 / 高频：** 需异步 IO 与架构调整，**当前** 为单交易对同步循环。

---

## 许可与责任

不作任何担保。实盘前请阅读 **[ARCHITECTURE.md](ARCHITECTURE.md)** 与币安 API 文档。
