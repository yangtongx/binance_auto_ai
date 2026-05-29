"""机器学习策略（可选装 ml-torch/ml-tf）：logits 三分类 → long/short/hold。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from futures_llm_bot.backtest.engine import Strategy
from futures_llm_bot.schemas import Action, LLMSignal

logger = logging.getLogger(__name__)


def _log_returns(closes: np.ndarray) -> np.ndarray:
    c = np.asarray(closes, dtype=np.float64)
    c = np.clip(c, 1e-12, None)
    lr = np.diff(np.log(c))
    return lr.astype(np.float64)


def _action_from_scores(hold: float, long_s: float, short_s: float) -> Action:
    scores = (hold, long_s, short_s)
    ix = int(np.argmax(scores))
    if ix == 1:
        return Action.LONG
    if ix == 2:
        return Action.SHORT
    return Action.HOLD


def _safe_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


class TorchScriptMLStrategy:
    """``torch.jit`` model: ``mlp`` expects ``[1, window-1]``; ``lstm`` / ``transformer`` expect ``[1, window-1, 1]``."""

    def __init__(
        self,
        model_path: Path,
        *,
        window: int,
        arch: str,
        size_pct: float,
        confidence: float,
        hot_reload: bool = False,
        hot_reload_interval_sec: float = 30.0,
    ) -> None:
        try:
            import torch
        except ImportError as e:  # pragma: no cover — 可选依赖
            raise RuntimeError('Install the ml-torch extra: pip install -e ".[ml-torch]"') from e
        key = arch.strip().lower()
        if key not in ("mlp", "lstm", "transformer"):
            raise ValueError(f"Unknown torch arch {arch!r}")
        self._torch = torch
        self._path = model_path
        self._model = torch.jit.load(str(model_path), map_location="cpu")
        self._model.eval()
        self._window = window
        self._arch = key
        self._size_pct = size_pct
        self._confidence = confidence
        self._feat = window - 1
        self._hot_reload = hot_reload
        self._hot_reload_interval_sec = float(hot_reload_interval_sec)
        self._last_check_mono = 0.0
        self._loaded_mtime_ns: int | None = _safe_mtime_ns(model_path)

    def reset(self) -> None:
        pass

    def _maybe_reload_torch(self) -> None:
        if not self._hot_reload:
            return
        now = time.monotonic()
        if now - self._last_check_mono < self._hot_reload_interval_sec:
            return
        self._last_check_mono = now
        mtime_ns = _safe_mtime_ns(self._path)
        if mtime_ns is None or mtime_ns == self._loaded_mtime_ns:
            return
        try:
            new_model = self._torch.jit.load(str(self._path), map_location="cpu")
            new_model.eval()
        except Exception as e:
            logger.warning("ml torch hot reload failed (%s); keeping previous model", e)
            return
        self._model = new_model
        self._loaded_mtime_ns = mtime_ns
        logger.info("ml torch model hot-reloaded from %s", self._path)

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        self._maybe_reload_torch()
        if len(ohlcv) < self._window:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="ml warmup")
        c = np.array([float(b[4]) for b in ohlcv[-self._window :]], dtype=np.float64)
        feat = _log_returns(c)
        if feat.size != self._feat:
            return LLMSignal(
                action=Action.HOLD,
                size_pct=0.0,
                confidence=self._confidence,
                reason=f"ml feat len {feat.size} != {self._feat}",
            )
        if self._arch == "mlp":
            x = self._torch.from_numpy(feat.reshape(1, -1)).float()
        else:
            x = self._torch.from_numpy(feat.reshape(1, -1, 1)).float()
        with self._torch.no_grad():
            out = self._model(x)
        y = out.squeeze()
        if y.dim() == 0:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="ml bad output")
        arr = y.detach().float().cpu().numpy().reshape(-1)
        if arr.size < 3:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="ml need 3 logits")
        act = _action_from_scores(float(arr[0]), float(arr[1]), float(arr[2]))
        if act == Action.HOLD:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="ml hold")
        return LLMSignal(
            action=act,
            size_pct=self._size_pct,
            confidence=self._confidence,
            reason=f"ml torch {self._arch}",
        )


class TensorFlowKerasMLStrategy:
    """Keras model (``.keras`` / SavedModel dir) expecting shape ``[1, F]`` log-returns (MLP only)."""

    def __init__(
        self,
        model_path: Path,
        *,
        window: int,
        size_pct: float,
        confidence: float,
        hot_reload: bool = False,
        hot_reload_interval_sec: float = 30.0,
    ) -> None:
        try:
            import tensorflow as tf  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError('Install the ml-tf extra: pip install -e ".[ml-tf]"') from e
        self._tf = tf
        self._path = model_path
        self._model: Any = tf.keras.models.load_model(str(model_path))
        self._window = window
        self._size_pct = size_pct
        self._confidence = confidence
        self._feat = window - 1
        self._hot_reload = hot_reload
        self._hot_reload_interval_sec = float(hot_reload_interval_sec)
        self._last_check_mono = 0.0
        self._loaded_mtime_ns: int | None = _safe_mtime_ns(model_path)

    def reset(self) -> None:
        pass

    def _maybe_reload_keras(self) -> None:
        if not self._hot_reload:
            return
        now = time.monotonic()
        if now - self._last_check_mono < self._hot_reload_interval_sec:
            return
        self._last_check_mono = now
        mtime_ns = _safe_mtime_ns(self._path)
        if mtime_ns is None or mtime_ns == self._loaded_mtime_ns:
            return
        try:
            new_model = self._tf.keras.models.load_model(str(self._path))
        except Exception as e:
            logger.warning("ml keras hot reload failed (%s); keeping previous model", e)
            return
        self._model = new_model
        self._loaded_mtime_ns = mtime_ns
        logger.info("ml keras model hot-reloaded from %s", self._path)

    def on_bar(self, _i: int, ohlcv: list[list[float]]) -> LLMSignal:
        self._maybe_reload_keras()
        if len(ohlcv) < self._window:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="ml warmup")
        c = np.array([float(b[4]) for b in ohlcv[-self._window :]], dtype=np.float64)
        feat = _log_returns(c).reshape(1, -1).astype(np.float32)
        if feat.shape[1] != self._feat:
            return LLMSignal(
                action=Action.HOLD,
                size_pct=0.0,
                confidence=self._confidence,
                reason=f"ml feat dim {feat.shape[1]} != {self._feat}",
            )
        out = self._model.predict(feat, verbose=0)
        arr = np.asarray(out, dtype=np.float64).reshape(-1)
        if arr.size < 3:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="ml need 3 outputs")
        act = _action_from_scores(float(arr[0]), float(arr[1]), float(arr[2]))
        if act == Action.HOLD:
            return LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=self._confidence, reason="ml hold")
        return LLMSignal(
            action=act,
            size_pct=self._size_pct,
            confidence=self._confidence,
            reason="ml tensorflow",
        )


def build_ml_strategy(
    *,
    backend: str,
    model_path: str | Path,
    window: int,
    size_pct: float,
    confidence: float,
    torch_arch: str = "mlp",
    hot_reload: bool = False,
    hot_reload_interval_sec: float = 30.0,
) -> Strategy:
    path = Path(model_path)
    if not path.exists():
        raise ValueError(f"ML_MODEL_PATH does not exist: {path}")
    key = backend.strip().lower()
    if key in ("torch", "pytorch"):
        return TorchScriptMLStrategy(
            path,
            window=window,
            arch=torch_arch,
            size_pct=size_pct,
            confidence=confidence,
            hot_reload=hot_reload,
            hot_reload_interval_sec=hot_reload_interval_sec,
        )
    if key in ("tensorflow", "tf", "keras"):
        return TensorFlowKerasMLStrategy(
            path,
            window=window,
            size_pct=size_pct,
            confidence=confidence,
            hot_reload=hot_reload,
            hot_reload_interval_sec=hot_reload_interval_sec,
        )
    raise ValueError(f"Unknown ML_BACKEND={backend!r} (use torch or tensorflow)")
