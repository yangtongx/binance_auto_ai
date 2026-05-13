"""Combine multiple rule strategies into one signal (ensemble / voting)."""

from __future__ import annotations

from collections.abc import Sequence

from futures_llm_bot.backtest.engine import Strategy
from futures_llm_bot.schemas import Action, LLMSignal


def _vote_numeric(s: LLMSignal) -> float:
    if s.action == Action.LONG:
        return 1.0
    if s.action == Action.SHORT:
        return -1.0
    return 0.0


class CompositeStrategy:
    """Run N child strategies each bar and merge via ``mode``.

    Children are invoked in order; all share the same ``ohlcv`` slice.
    """

    def __init__(
        self,
        children: Sequence[Strategy],
        mode: str,
        weights: Sequence[float] | None = None,
    ) -> None:
        if not children:
            raise ValueError("composite needs at least one child strategy")
        m = mode.strip().lower()
        if m not in ("majority", "weighted", "unanimous", "first"):
            raise ValueError("composite mode must be majority|weighted|unanimous|first")
        if m == "weighted":
            if weights is None or len(weights) != len(children):
                raise ValueError("weighted mode requires weights with same length as children")
            if sum(weights) <= 0:
                raise ValueError("sum of weights must be > 0")
        self._children = list(children)
        self._mode = m
        self._weights = list(weights) if weights is not None else None

    def reset(self) -> None:
        for c in self._children:
            c.reset()

    def on_bar(self, i: int, ohlcv: list[list[float]]) -> LLMSignal:
        signals = [c.on_bar(i, ohlcv) for c in self._children]

        if self._mode == "first":
            for s in signals:
                if s.action not in (Action.HOLD,):
                    return LLMSignal(
                        action=s.action,
                        size_pct=s.size_pct,
                        confidence=min(1.0, max(0.0, s.confidence)),
                        reason=f"composite:first:{s.reason}"[:2000],
                    )
            s0 = signals[-1]
            return LLMSignal(
                action=Action.HOLD,
                size_pct=0.0,
                confidence=s0.confidence,
                reason="composite:first:all_hold",
            )

        if self._mode == "unanimous":
            non_hold = [s for s in signals if s.action != Action.HOLD]
            if not non_hold:
                ref = signals[0]
                return LLMSignal(
                    action=Action.HOLD,
                    size_pct=0.0,
                    confidence=ref.confidence,
                    reason="composite:unanimous:all_hold",
                )
            actions_set = {s.action for s in non_hold}
            if len(actions_set) != 1:
                ref = signals[0]
                return LLMSignal(
                    action=Action.HOLD,
                    size_pct=0.0,
                    confidence=ref.confidence,
                    reason="composite:unanimous:disagree",
                )
            only = non_hold[0].action
            conf = min(s.confidence for s in non_hold)
            size = min(s.size_pct for s in non_hold)
            return LLMSignal(
                action=only,
                size_pct=size,
                confidence=conf,
                reason=f"composite:unanimous:{only.value}",
            )

        if self._mode == "weighted":
            assert self._weights is not None
            acc = 0.0
            wsum = 0.0
            conf_acc = 0.0
            for s, w in zip(signals, self._weights, strict=True):
                acc += w * _vote_numeric(s) * s.confidence
                wsum += w
                conf_acc += w * s.confidence
            score = acc / wsum if wsum else 0.0
            avg_conf = conf_acc / wsum if wsum else 0.0
            thr = 0.25
            if score > thr:
                return LLMSignal(
                    action=Action.LONG,
                    size_pct=signals[0].size_pct,
                    confidence=min(1.0, avg_conf),
                    reason=f"composite:weighted:score={score:.2f}",
                )
            if score < -thr:
                return LLMSignal(
                    action=Action.SHORT,
                    size_pct=signals[0].size_pct,
                    confidence=min(1.0, avg_conf),
                    reason=f"composite:weighted:score={score:.2f}",
                )
            return LLMSignal(
                action=Action.HOLD,
                size_pct=0.0,
                confidence=min(1.0, avg_conf),
                reason=f"composite:weighted:neutral={score:.2f}",
            )

        # majority
        long_v = sum(1 for s in signals if s.action == Action.LONG)
        short_v = sum(1 for s in signals if s.action == Action.SHORT)
        flat_v = sum(1 for s in signals if s.action == Action.FLAT)
        n = len(signals)
        if flat_v > n // 2:
            ref = next(s for s in signals if s.action == Action.FLAT)
            return LLMSignal(
                action=Action.FLAT,
                size_pct=ref.size_pct,
                confidence=ref.confidence,
                reason="composite:majority:flat",
            )
        if long_v > short_v and long_v > n // 2:
            conf = min(s.confidence for s in signals if s.action == Action.LONG)
            size = min(s.size_pct for s in signals if s.action == Action.LONG)
            return LLMSignal(
                action=Action.LONG,
                size_pct=size,
                confidence=conf,
                reason="composite:majority:long",
            )
        if short_v > long_v and short_v > n // 2:
            conf = min(s.confidence for s in signals if s.action == Action.SHORT)
            size = min(s.size_pct for s in signals if s.action == Action.SHORT)
            return LLMSignal(
                action=Action.SHORT,
                size_pct=size,
                confidence=conf,
                reason="composite:majority:short",
            )
        ref = signals[0]
        return LLMSignal(
            action=Action.HOLD,
            size_pct=0.0,
            confidence=ref.confidence,
            reason="composite:majority:no_clear_winner",
        )
