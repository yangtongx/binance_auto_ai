# futures-llm-bot

**语言:** [English](README.md) · [中文](README.zh.md)

**futures-llm-bot** 是一个面向 **币安 USDT-M（USDⓈ-M / U 本位）线性永续合约** 的 Python 程序。它在固定周期内：**拉行情与账户状态 → 生成交易信号 → 经过风控与会话限制 → 通过 CCXT 下单**，支持 **单向持仓（one-way）** 与 **双向持仓（hedge）** 两种模式。

信号有两种来源：

1. **`SIGNAL_SOURCE=strategy`（默认）** — 使用与内置回测 **完全一致** 的规则类：**均线交叉、RSI、MACD、布林带** 等，不调用大模型。
2. **`SIGNAL_SOURCE=llm`** — 将 **OHLCV** 与 **账户上下文**（持仓、钱包、持仓模式等）发给 **OpenAI 兼容** 的 Chat API（如 OpenAI、DeepSeek、Azure），解析严格 **JSON** 为交易信号。

仓库还包含：**教学向简化回测**、基于交易所流水的 **真实盈亏汇总 CLI**（`futures-llm-real-pnl`）、可选的 **HTTP 可观测性** 与 **简易仪表盘**，以及核心路径的 **pytest** 测试。

> **免责声明：** 本项目为 **实验性** 软件，**合约交易风险极高**。请在充分理解行为前优先使用 **测试网** 与 **`DRY_RUN=true`**。API Key、配置与亏损由使用者自行承担。**内置回测的 PnL 为简化模型，不能替代交易所账单级真实盈亏。**

---

## 功能一览

| 模块 | 说明 |
|------|------|
| **下单执行** | `ccxt.binanceusdm`；支持测试网/主网；单向与双向持仓分支逻辑 |
| **信号** | 与 `futures-llm-backtest` 对齐的规则策略，或 LLM 输出的 `LLMSignal` |
| **风控** | `MIN_CONFIDENCE`、名义上限 `MAX_NOTIONAL_USDT`、可选 UTC 自然日 **日交易次数 / 日亏损** 限制 |
| **会话状态** | JSON `STATE_FILE`，跨进程用 `filelock` |
| **回测** | CSV 或 CCXT 拉取；按 Bar **收盘价** 近似成交 + `fee_bps`；**不含** 完整资金费/保证金/强平等仿真 |
| **真实 PnL** | 拉取 `/fapi/v1/income` 汇总已实现盈亏、资金费、手续费等 |
| **可观测性** | 可选 `GET /`、`/dashboard`、`/health`、`/metrics` |
| **开发体验** | Pydantic 配置、`pyproject.toml` 中 Pyright 路径、`--smoke` 自检 |

---

## 架构（简述）

1. **`cli.run_loop`** 在默认 **1 分钟** 周期边界触发（`--once` 则只跑一轮）。
2. **Tick** 读取 **USDT 权益**、**持仓**，按需 **K 线**，再走 **`strategy_factory`** 或 **`llm_decide`**。
3. **`risk.assess_signal`** 过滤信号；**`session_risk`** 可按 UTC 日限制新开多/空。
4. **`execution`** 解析持仓模式，经 **`order_utils`** 下单，真实报单可记 **metrics**。

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

安装后可使用入口命令：

| 命令 | 作用 |
|------|------|
| `futures-llm-bot` | 主交易循环 |
| `futures-llm-backtest` | 规则回测（CSV 或 `--fetch`） |
| `futures-llm-real-pnl` | 币安 USDT-M **收入 / income** 汇总 |

若未执行 `pip install -e .`，可设置 **`PYTHONPATH=src`** 后使用 `python -m futures_llm_bot`。

---

## 配置说明

将 **`.env.example`** 复制为 **`.env`**（从仓库根目录加载）。主要分组：

- **币安：** `BINANCE_API_KEY`、`BINANCE_API_SECRET`、`BINANCE_TESTNET`  
- **LLM（`SIGNAL_SOURCE=llm`）：** `OPENAI_API_KEY`、可选 `OPENAI_BASE_URL`、`OPENAI_MODEL`、超时与重试  
- **交易：** `SYMBOL`（如 `BTC/USDT:USDT`）、`TIMEFRAME`、`KLINES_LIMIT`、`MAX_NOTIONAL_USDT`、`DRY_RUN`、`MIN_CONFIDENCE`  
- **规则信号：** `STRATEGY_NAME`（`sma_cross`、`rsi`、`macd`、`bollinger` / `bb`）及 **`.env.example`** 中对应 `STRATEGY_*`  
- **持仓 / HTTP：** `POSITION_MODE`、`EXCHANGE_TIMEOUT_MS`、`POSITION_POLL_*`  
- **会话风控：** `MAX_TRADES_PER_DAY`、`MAX_DAILY_LOSS_USDT`、`STATE_FILE`、`DAILY_LOSS_WARN_RATIO`  
- **可观测性：** `OBSERVABILITY_HOST`、`OBSERVABILITY_PORT`（非 0 则启用内置页面与 JSON/Prometheus）

**`FLAT` / `HOLD`** 不受日交易笔数、日亏损上限阻挡，便于减仓/	exit。

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
- 参数与回测 **`--fast` / `--slow` / `--rsi-period` / …** 一一对应，便于 **回测 → 实盘** 对齐。

### LLM 模式（`SIGNAL_SOURCE=llm`）

- 拼装 **最近 K 线表格 + 账户上下文** 文本。  
- **`llm_strategy.llm_decide`** 带重试；输出校验为 **`LLMSignal`**。  
- 通过 `OPENAI_BASE_URL` 可接 **DeepSeek** 等兼容端点。

---

## 内置规则策略

| `STRATEGY_NAME` | 思路 | 主要参数 |
|-----------------|------|----------|
| `sma_cross` | 快均线与慢均线交叉 | `STRATEGY_FAST`、`STRATEGY_SLOW` |
| `rsi` | RSI 超卖/超买区 | `STRATEGY_RSI_PERIOD`、超买超卖阈值 |
| `macd` | MACD 线与信号线交叉 | 快慢周期 + `STRATEGY_MACD_SIGNAL` |
| `bollinger` / `bb` | 价格穿上下轨 | `STRATEGY_BB_PERIOD`、`STRATEGY_BB_STD` |

统一输出 **`LLMSignal`**，**风控与执行** 在 LLM 与规则之间复用。

---

## 回测（`futures-llm-backtest`）

```bash
futures-llm-backtest --fetch --timeframe 1h --limit 800 --strategy sma_cross --fast 10 --slow 30
futures-llm-backtest --fetch --strategy rsi --rsi-period 14 --limit 600
futures-llm-backtest --csv path/to/ohlcv.csv --strategy macd --fast 12 --slow 26 --macd-signal 9
```

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
| `src/futures_llm_bot/` | 主包（`cli`、`execution`、`backtest`、`strategy_factory`、`observability` 等） |
| `tests/` | Pytest |
| `ARCHITECTURE.md` | 模块与数据流（英文） |
| `.env.example` | 环境变量模板 |

---

## 扩展与后续方向

- **新策略：** 实现 `reset` / `on_bar` → `LLMSignal`，在 **`strategy_factory`** 注册。  
- **告警：** 外部抓取 **`/metrics`** 或轮询 **`/health`**，对接 PagerDuty / Slack 等。  
- **多品种 / 高频：** 需异步 IO 与架构调整，**当前** 为单交易对同步循环。

---

## 许可与责任

不作任何担保。实盘前请阅读 **[ARCHITECTURE.md](ARCHITECTURE.md)** 与币安 API 文档。
