# 代码导读（中文）

> **初学者请先读 [BEGINNER_ZH.md](BEGINNER_ZH.md)**（阅读顺序、流程图、一分钟 tick 拆解）。

## 主流程（必读）

| 顺序 | 模块 | 说明 |
|------|------|------|
| 1 | `cli.py` | 主循环 `run_loop` → 每分钟 `_tick` |
| 2 | `symbol_universe.py` | `CandidatePool` 自动/手动候选池；`select_top_usdm_candidates` 复合排名（含 `momentum`/`funding`/`cg_oi_change`，rank 百分位归一化；CoinGlass 资金费率过滤） |
| 2.5 | `coinglass.py` | 可选 CoinGlass V4 客户端：聚合 OI 变化/资金费率（`COINGLASS_*`，失败降级） |
| 3 | `symbol_picker.py` | 扫信号、选最强、`plan_signal_pick_trades` 平仓/换币（含 `SYMBOL_ROTATION_HYSTERESIS` 换币迟滞） |
| 4 | `active_exit.py` | 主动离场：`held_exit_signal` / `ExitTracker`（止损/止盈/移动止盈/超时 + **ROE 止盈止损** `EXIT_*`，优先于策略） |
| 5 | `strategy_factory.py` + `backtest/strategies.py` | 规则策略 `on_bar` |
| 6 | `risk.py` + `session_risk.py` | 置信度 + 日笔数/日亏损 |
| 7 | `execution*.py` + `execution_helpers.py` | 单向/双向下单；名义/保证金计算（`POSITION_SIZING`、`LEVERAGE_MODE=max` 按币解析最大杠杆） |
| 8 | `order_utils.py` | `place_order`、`DRY_RUN` |

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
| `binance-auto-ai` | `cli.py` / `__main__.py` |
| `binance-auto-signal` | `signal_cli.py` |
| `binance-auto-backtest` | `backtest_cli.py` |
| `binance-auto-real-pnl` | `real_pnl_cli.py` |
| `binance-auto-var-validate` | `var_validation_cli.py` |
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
