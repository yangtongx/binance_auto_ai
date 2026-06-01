"""数值容差：判断「是否已平仓」、标记价格是否异常（非交易所最小下单量）。"""

# 单向净仓 |contracts| 低于此视为空仓
NET_POSITION_EPS_CONTRACTS = 1e-12

# 双向单腿平仓后轮询：低于此视为该腿已平
LEG_POSITION_EPS_CONTRACTS = 1e-9

# 标记价合理范围，超出视为 ticker 异常
MIN_SANE_MARK_USDT = 1e-12
MAX_SANE_MARK_USDT = 1e12
