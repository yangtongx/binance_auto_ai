"""RL 训练环境（Gymnasium）：单资产 K 线 → 离散仓位 {空、平、多}。"""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces


class FuturesPerpBarEnv(gym.Env):
    """
    每步一根 K 线；观测与实盘 RL 策略一致（window-1 个裁剪对数收益）。

    动作：目标净仓位 {-1, 0, +1}（空/平/多）。
    奖励：pnl | pnl_cost（换手惩罚）| risk_adjusted（回撤惩罚）。
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        closes: np.ndarray,
        window: int,
        *,
        reward: str = "pnl",
        trans_cost: float = 0.0,
        episode_len: int = 256,
        random_start: bool = True,
        drawdown_penalty: float = 0.5,
    ) -> None:
        super().__init__()
        if window < 4:
            raise ValueError("window must be >= 4")
        self._closes = np.asarray(closes, dtype=np.float64).reshape(-1)
        if self._closes.size < window + episode_len + 5:
            raise ValueError("closes series too short for window + episode")
        self._lr = np.diff(np.log(np.maximum(self._closes, 1e-12)))
        if reward not in ("pnl", "pnl_cost", "risk_adjusted"):
            raise ValueError("reward must be pnl|pnl_cost|risk_adjusted")
        self._reward = reward
        self._trans = float(trans_cost)
        self._episode_len = int(episode_len)
        self._random_start = bool(random_start)
        self._dd_pen = float(drawdown_penalty)
        self._window = int(window)

        d_obs = window - 1
        self.observation_space = spaces.Box(
            low=-5.0,
            high=5.0,
            shape=(d_obs,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(3)

        self._i: int = 0
        self._pos: int = 0
        self._steps: int = 0
        self._log_eq: float = 0.0
        self._peak_log_eq: float = 0.0

    def _obs_at(self, end_idx: int) -> np.ndarray:
        seg = self._closes[end_idx - self._window + 1 : end_idx + 1]
        lr = np.diff(np.log(np.maximum(seg, 1e-12)))
        lr = np.clip(lr, -5.0, 5.0)
        return lr.astype(np.float32)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict | None = None,
    ) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        lo = self._window - 1
        hi = int(self._closes.size) - 1 - self._episode_len
        hi = max(lo, hi)
        if self._random_start and self.np_random is not None and hi > lo:
            start = int(self.np_random.integers(lo, hi + 1))
        else:
            start = lo
        self._i = start
        self._pos = 0
        self._steps = 0
        self._log_eq = 0.0
        self._peak_log_eq = 0.0
        return self._obs_at(self._i), {}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        target = (0, 1, -1)[int(action)]
        r = float(self._lr[self._i])
        turnover = float(abs(target - self._pos))
        pnl = float(target) * r
        rew = pnl
        if self._reward == "pnl_cost":
            rew -= self._trans * turnover
        elif self._reward == "risk_adjusted":
            self._log_eq += pnl
            self._peak_log_eq = max(self._peak_log_eq, self._log_eq)
            dd = max(0.0, self._peak_log_eq - self._log_eq)
            rew = pnl - self._dd_pen * dd
        self._pos = int(target)
        self._i += 1
        self._steps += 1

        truncated = bool(
            self._steps >= self._episode_len or self._i >= len(self._closes) - 1
        )
        terminated = False
        end_idx = min(self._i, len(self._closes) - 1)
        obs = self._obs_at(end_idx)
        info = {"r": r, "pos": self._pos}
        return obs, float(rew), terminated, truncated, info
