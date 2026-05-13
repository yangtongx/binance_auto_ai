"""Optional Stable-Baselines3 inference (Discrete {hold, long, short} -> LLMSignal)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from futures_llm_bot.schemas import Action, LLMSignal


def build_observation_vector(closes: list[float] | np.ndarray, window: int) -> np.ndarray:
    """Match training default: last ``window`` closes -> ``window-1`` clipped log-returns."""
    c = np.asarray(closes, dtype=np.float64)
    if c.size < window:
        raise ValueError("not enough closes for RL window")
    seg = c[-window:]
    lr = np.diff(np.log(np.maximum(seg, 1e-12)))
    lr = np.clip(lr, -5.0, 5.0)
    return lr.astype(np.float32)


class RlSb3Strategy:
    """Load a SB3 model (e.g. PPO) and map discrete actions 0/1/2 -> hold/long/short."""

    def __init__(
        self,
        model: Any,
        *,
        window: int,
        size_pct: float = 100.0,
        confidence: float = 0.75,
    ) -> None:
        self._model = model
        self._window = int(window)
        self._size_pct = float(size_pct)
        self._confidence = float(confidence)

    def reset(self) -> None:
        pass

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        closes = [float(b[4]) for b in ohlcv]
        if len(closes) < self._window:
            return LLMSignal(
                action=Action.HOLD,
                size_pct=0.0,
                confidence=self._confidence,
                reason="rl:warmup",
            )
        obs = build_observation_vector(closes, self._window)
        action, _info = self._model.predict(obs, deterministic=True)
        ai = int(np.asarray(action).reshape(-1)[0])
        if ai == 1:
            return LLMSignal(
                action=Action.LONG,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="rl:long",
            )
        if ai == 2:
            return LLMSignal(
                action=Action.SHORT,
                size_pct=self._size_pct,
                confidence=self._confidence,
                reason="rl:short",
            )
        return LLMSignal(
            action=Action.HOLD,
            size_pct=0.0,
            confidence=self._confidence,
            reason="rl:hold",
        )


def load_sb3_strategy(
    model_path: str | Path,
    *,
    window: int,
    size_pct: float = 100.0,
    confidence: float = 0.75,
) -> RlSb3Strategy:
    try:
        from stable_baselines3.common.base_class import BaseAlgorithm
    except ImportError as e:  # pragma: no cover - optional dependency
        raise ImportError(
            "RL strategies require optional deps: pip install -e \".[rl]\" "
            "(stable-baselines3 + gymnasium).",
        ) from e

    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"RL model not found: {path}")
    model = BaseAlgorithm.load(path)
    return RlSb3Strategy(model, window=window, size_pct=size_pct, confidence=confidence)
