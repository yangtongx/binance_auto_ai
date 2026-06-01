"""交易信号数据结构：策略与 LLM 输出的统一格式。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Action(str, Enum):
    """下一根 K 线建议动作。"""

    LONG = "long"  # 做多
    SHORT = "short"  # 做空
    FLAT = "flat"  # 平仓（reduceOnly 清掉净仓）
    HOLD = "hold"  # 观望，不下单


class LLMSignal(BaseModel):
    """结构化交易信号；下单前经 Pydantic 校验。"""

    action: Action
    size_pct: float = Field(
        ge=0.0,
        le=100.0,
        description="意向仓位占 sizing 基数的百分比（见 POSITION_SIZING / MAX_NOTIONAL_USDT）",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="置信度，低于 MIN_CONFIDENCE 不开仓")
    reason: str = Field(default="", max_length=2000, description="策略或 LLM 给出的简短原因")
