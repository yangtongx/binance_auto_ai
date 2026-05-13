from __future__ import annotations

from dataclasses import dataclass

from futures_llm_bot.schemas import Action, LLMSignal


@dataclass
class RiskDecision:
    allowed: bool
    message: str


def assess_signal(signal: LLMSignal, min_confidence: float) -> RiskDecision:
    if signal.action == Action.HOLD:
        return RiskDecision(True, "hold always allowed")

    # Exiting / reducing exposure should not be gated on model confidence.
    if signal.action == Action.FLAT:
        return RiskDecision(True, "flat always allowed")

    if signal.confidence < min_confidence:
        return RiskDecision(False, f"confidence {signal.confidence:.2f} < {min_confidence}")

    if signal.action in (Action.LONG, Action.SHORT) and signal.size_pct <= 0:
        return RiskDecision(False, "size_pct must be > 0 for directional trades")

    return RiskDecision(True, "ok")
