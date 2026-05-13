from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Action(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"
    HOLD = "hold"


class LLMSignal(BaseModel):
    """Structured decision from the LLM; validated before any exchange call."""

    action: Action
    size_pct: float = Field(ge=0.0, le=100.0, description="Intent size as % of MAX_NOTIONAL_USDT")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=2000)
