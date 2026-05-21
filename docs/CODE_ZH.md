# 代码导读（中文）

## 主流程（必读）

| 顺序 | 模块 | 说明 |
|------|------|------|
| 1 | `cli.py` | 主循环 `run_loop` → 每分钟 `_tick` |
| 2 | `symbol_universe.py` | `CandidatePool` 自动/手动候选池 |
| 3 | `symbol_picker.py` | 扫信号、选最强、`plan_signal_pick_trades` 平仓/换币 |
| 4 | `strategy_factory.py` + `backtest/strategies.py` | 规则策略 `on_bar` |
| 5 | `risk.py` + `session_risk.py` | 置信度 + 日笔数/日亏损 |
| 6 | `execution*.py` | 单向/双向下单、名义金额 |
| 7 | `order_utils.py` | `place_order`、`DRY_RUN` |

## 信号与数据结构

- `schemas.py`：`Action`（long/short/flat/hold）、`LLMSignal`
- `llm_strategy.py`：`SIGNAL_SOURCE=llm`
- `composite_strategy.py` / `ml_signal_strategy.py` / `rl_signal_strategy.py`：扩展策略

## 技术指标

- `backtest/indicators.py`：SMA/RSI/MACD/布林等；`SMACrossStream` 等增量类供实盘用
- `risk_metrics.py`：VaR 尾部门控 `var_tail_block_reason_from_ohlcv`

## 诊币（不下单）

- `signal_probe.py` → `/api/signal`
- `signal_timing_hints.py`：观望时的具体价位
- `symbol_input.py`：用户输入解析

## 监控与通知

- `observability.py`、`dashboard_html.py`、`dashboard_state.py`
- `telegram_notify.py`、`telegram_format.py`
- `metrics.py`：`/health`、`/metrics`

## 命令行工具

| 命令 | 模块 |
|------|------|
| `futures-llm-bot` | `cli.py` / `__main__.py` |
| `futures-llm-signal` | `signal_cli.py` |
| `futures-llm-backtest` | `backtest_cli.py` |
| `futures-llm-real-pnl` | `real_pnl_cli.py` |
| `futures-llm-var-validate` | `var_validation_cli.py` |
| 验密钥 | `verify_binance_cli.py` |

## 回测与 RL

- `backtest/engine.py`、`backtest/data.py`
- `rl/futures_perp_env.py`：训练环境（可选依赖）

## 配置

- 模板：`deploy/server.env`
- 加载：`config.py` → `Settings`

## 实盘参数速查

- 名义金额：`execution_helpers.directional_notional_or_skip`（`POSITION_SIZING` × `LEVERAGE` × `STRATEGY_SIZE_PCT`）
- 硬顶：`MAX_NOTIONAL_USDT`
- 持仓模式：`POSITION_MODE=auto`（避免 -4061）
