# 代码导读（中文）

## 主流程

1. **`cli.py`**：`run_loop` 每分钟 `_tick` → 规则/LLM 出信号 → 风控 → `execute_signal` 下单。
2. **`symbol_universe.py`**：`CandidatePool` 维护 `signal_pick` 自动/手动候选池。
3. **`symbol_picker.py`**：扫描各币信号、`plan_signal_pick_trades` 规划平仓/换币/开仓。
4. **`execution*.py`**：按单向/双向持仓模式执行 flat/long/short。
5. **`execution_helpers.py`**：`directional_notional_or_skip` 计算名义金额，`open_market_within_notional_cap` 受 `MAX_NOTIONAL_USDT` 限制。

## 信号与风控

| 模块 | 作用 |
|------|------|
| `schemas.py` | `Action`、`LLMSignal` |
| `strategy_factory.py` | 规则策略实例（如 `sma_cross`） |
| `llm_strategy.py` | `SIGNAL_SOURCE=llm` 时调用大模型 |
| `risk.py` | `MIN_CONFIDENCE` 门槛 |
| `session_risk.py` | 日笔数、日最大亏损 |

## 诊币（不下单）

| 模块 | 作用 |
|------|------|
| `signal_probe.py` | `/api/signal`、手动分析 |
| `signal_timing_hints.py` | 观望时做多/做空价位参考 |
| `symbol_input.py` | 用户输入币种解析 |

## 配置

- 生产模板：`deploy/server.env`
- 加载逻辑：`config.py` → `Settings`

## 监控

- `observability.py` + `dashboard_html.py` + `dashboard_state.py`
