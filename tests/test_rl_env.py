from __future__ import annotations

import numpy as np
import pytest

gymnasium = pytest.importorskip("gymnasium")


def test_futures_perp_env_smoke():
    from futures_llm_bot.rl.futures_perp_env import FuturesPerpBarEnv

    c = 100_000 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.001, size=800)))
    env = FuturesPerpBarEnv(c, window=32, episode_len=64)
    obs, _ = env.reset(seed=0)
    assert obs.shape == (31,)
    for _ in range(10):
        obs, rew, term, trunc, info = env.step(env.action_space.sample())
        assert "r" in info
        if trunc or term:
            break
