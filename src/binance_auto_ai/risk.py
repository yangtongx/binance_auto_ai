"""信号级风控：置信度与仓位比例门槛（不含日亏损/日笔数，见 session_risk）。"""

from __future__ import annotations

from dataclasses import dataclass

from binance_auto_ai.schemas import Action, LLMSignal


@dataclass
class RiskDecision:
    """是否允许按该信号下单。"""

    allowed: bool
    message: str


def assess_signal(signal: LLMSignal, min_confidence: float) -> RiskDecision:
    """检查 long/short 是否满足 MIN_CONFIDENCE；hold/flat 始终放行。"""
    if signal.action == Action.HOLD:
        return RiskDecision(True, "hold always allowed")

    # 平仓不卡置信度
    if signal.action == Action.FLAT:
        return RiskDecision(True, "flat always allowed")

    if signal.confidence < min_confidence:
        return RiskDecision(False, f"confidence {signal.confidence:.2f} < {min_confidence}")

    if signal.action in (Action.LONG, Action.SHORT) and signal.size_pct <= 0:
        return RiskDecision(False, "size_pct must be > 0 for directional trades")

    return RiskDecision(True, "ok")
