"""将策略/系统信号的 reason 转为中文（主要用于 Telegram 展示）。"""

from __future__ import annotations

import re

# 策略 reason 精确匹配（英文原文 -> 中文）
_REASON_EXACT: dict[str, str] = {
    "warmup": "指标预热中",
    "fast cross above": "快线上穿慢线（金叉）",
    "fast cross below": "快线下穿慢线（死叉）",
    "no cross": "无均线交叉",
    "rsi mid": "RSI 中性区",
    "rsi mid(vol)": "RSI 中性区（波动率自适应）",
    "macd cross up": "MACD 金叉",
    "macd cross down": "MACD 死叉",
    "macd no cross": "MACD 无交叉",
    "bb cross below lower": "价格跌破布林下轨",
    "bb cross above upper": "价格突破布林上轨",
    "bb inside": "价格在布林带内",
    "ichimoku no signal": "一目均衡无信号",
    "fib no cross": "斐波那契无穿越",
    "vp na": "成交量分布数据不足",
    "vp no break": "未突破成交量分布中枢",
    "stoch no signal": "随机指标无信号",
    "atr inside": "价格在 ATR 通道内",
    "ml warmup": "模型预热中",
    "ml hold": "模型观望",
    "ml bad output": "模型输出异常",
    "ml need 3 logits": "模型输出维度错误",
    "ml need 3 outputs": "模型输出维度错误",
    "ml tensorflow": "TensorFlow 模型信号",
    "rl:warmup": "强化学习预热",
    "rl:long": "强化学习做多",
    "rl:short": "强化学习做空",
    "rl:hold": "强化学习观望",
    "composite:first:all_hold": "组合策略·首子策略均观望",
    "composite:unanimous:all_hold": "组合策略·一致观望",
    "composite:unanimous:disagree": "组合策略·子策略分歧",
    "composite:majority:flat": "组合策略·多数派平仓",
    "composite:majority:long": "组合策略·多数派做多",
    "composite:majority:short": "组合策略·多数派做空",
    "composite:majority:no_clear_winner": "组合策略·无明确多数",
    "composite:weighted:neutral": "组合策略·加权中性",
    "missing bar": "K 线数据缺失",
}

_RE_RSI_LOW = re.compile(r"^rsi<([\d.]+)$")
_RE_RSI_HIGH = re.compile(r"^rsi>([\d.]+)$")
_RE_RSI_LOW_VOL = re.compile(r"^rsi<([\d.]+)\(vol\)$")
_RE_RSI_HIGH_VOL = re.compile(r"^rsi>([\d.]+)\(vol\)$")
_RE_RL_ARCH = re.compile(r"^ml torch (.+)$")
_RE_ML_FEAT = re.compile(r"^ml feat (?:len|dim) (\d+) != (\d+)$")
_RE_COMPOSITE_FIRST = re.compile(r"^composite:first:(.+)$", re.DOTALL)
_RE_COMPOSITE_UNANIMOUS = re.compile(r"^composite:unanimous:(.+)$")
_RE_COMPOSITE_WEIGHTED = re.compile(r"^composite:weighted:score=([-\d.]+)$")
_RE_VAR = re.compile(r"^var_blocked:\s*(.+)$", re.DOTALL)


def reason_to_zh(reason: str | None) -> str:
    if not reason or not str(reason).strip():
        return "—"
    raw = str(reason).strip()

    if raw in _REASON_EXACT:
        return _REASON_EXACT[raw]

    m = _RE_RSI_LOW.match(raw)
    if m:
        return f"RSI 低于 {m.group(1)}（超卖做多）"
    m = _RE_RSI_HIGH.match(raw)
    if m:
        return f"RSI 高于 {m.group(1)}（超买做空）"
    m = _RE_RSI_LOW_VOL.match(raw)
    if m:
        return f"RSI 低于 {m.group(1)}（波动率自适应·超卖）"
    m = _RE_RSI_HIGH_VOL.match(raw)
    if m:
        return f"RSI 高于 {m.group(1)}（波动率自适应·超买）"

    if raw == "rsi_vol:warmup":
        return "RSI 波动率自适应预热中"

    m = _RE_RL_ARCH.match(raw)
    if m:
        return f"PyTorch 模型信号（{m.group(1)}）"

    m = _RE_ML_FEAT.match(raw)
    if m:
        return f"模型特征维度不符（{m.group(1)} ≠ {m.group(2)}）"

    m = _RE_COMPOSITE_FIRST.match(raw)
    if m:
        return f"组合策略·采用首信号：{reason_to_zh(m.group(1))}"

    m = _RE_COMPOSITE_UNANIMOUS.match(raw)
    if m:
        tail = m.group(1)
        if tail in ("long", "short", "flat", "hold"):
            action = {"long": "做多", "short": "做空", "flat": "平仓", "hold": "观望"}[tail]
            return f"组合策略·子策略一致·{action}"
        return f"组合策略·一致·{tail}"

    m = _RE_COMPOSITE_WEIGHTED.match(raw)
    if m:
        return f"组合策略·加权得分 {m.group(1)}"

    if raw.startswith("composite:weighted:neutral="):
        return f"组合策略·加权中性 {raw.split('=', 1)[-1]}"

    if raw.startswith("ichimoku tk cross up"):
        return "一目均衡转换线上穿（云上）"
    if raw.startswith("ichimoku tk cross down"):
        return "一目均衡转换线下穿（云下）"
    if raw.startswith("fib reclaim up"):
        return f"斐波那契向上突破（{raw.split('(', 1)[-1].rstrip(')')}）"
    if raw.startswith("fib reclaim down"):
        return f"斐波那契向下突破（{raw.split('(', 1)[-1].rstrip(')')}）"
    if raw == "vp break above poc":
        return "突破成交量分布 POC（上方）"
    if raw == "vp break below poc":
        return "跌破成交量分布 POC（下方）"
    if raw == "stoch cross up from oversold":
        return "随机指标超卖区金叉"
    if raw == "stoch cross down from overbought":
        return "随机指标超买区死叉"
    if raw == "atr breakout up":
        return "ATR 向上突破"
    if raw == "atr breakout down":
        return "ATR 向下突破"

    if raw.startswith("signal_pick: flat non-whitelist"):
        return "持仓不在候选池，强制平仓"
    if raw.startswith("signal_pick: rotate to "):
        sym = raw.split("rotate to ", 1)[-1].strip()
        return f"换币 → {sym.split(':', 1)[0] if sym else sym}"

    m = _RE_VAR.match(raw)
    if m:
        return f"VaR 风控拦截：{m.group(1)}"

    if raw.startswith("active_exit:"):
        return _active_exit_to_zh(raw[len("active_exit:") :].strip())

    return raw


def _active_exit_to_zh(detail: str) -> str:
    if detail.startswith("stop_loss "):
        return f"主动止损 · {detail}"
    if detail.startswith("stop_loss_roe "):
        return f"主动止损（ROE）· {detail}"
    if detail.startswith("take_profit "):
        return f"主动止盈 · {detail}"
    if detail.startswith("take_profit_roe "):
        return f"主动止盈（ROE）· {detail}"
    if detail.startswith("trailing "):
        return f"移动止盈 · {detail}"
    if detail.startswith("max_hold "):
        return f"持仓超时 · {detail}"
    if detail.startswith("cg_oi_drop "):
        return f"CoinGlass OI 骤降落袋 · {detail}"
    if detail.startswith("cg_adverse_funding "):
        return f"CoinGlass 资金费率拥挤 · {detail}"
    if detail.startswith("cg_crowd_top_account "):
        return f"CoinGlass 大户账号多空比拥挤 · {detail}"
    if detail.startswith("cg_crowd_top_position "):
        return f"CoinGlass 大户持仓多空比拥挤 · {detail}"
    if detail.startswith("cg_crowd_global "):
        return f"CoinGlass 全市场人数多空比拥挤 · {detail}"
    if detail.startswith("cg_net_against "):
        return f"CoinGlass 净仓逆向 · {detail}"
    if detail.startswith("cg_liq_cluster "):
        return f"CoinGlass 清算簇磁吸 · {detail}"
    return f"主动离场 · {detail}"
