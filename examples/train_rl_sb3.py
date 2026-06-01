#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""Train a Stable-Baselines3 agent (PPO) for ``STRATEGY_NAME=rl_sb3`` (discrete hold/long/short).

Requires: ``pip install -e ".[rl]"`` (stable-baselines3 + gymnasium).

**Observation** matches live inference: last ``window`` closes → ``window-1`` clipped log-returns (float32).

**Actions:** 0=flat, 1=long, 2=short (target position for next bar’s log return).

**Reward modes:**
  - ``pnl`` — position × next log return
  - ``pnl_cost`` — subtract turnover × ``--trans-cost``
  - ``risk_adjusted`` — PnL minus drawdown penalty on a simple cumulative log-PnL trace

Data sources (same spirit as ``train_ml_torch.py``): synthetic random walk, ``--csv``, or ``--fetch`` (paginated CCXT).

Example::

    pip install -e ".[rl]"
    python examples/train_rl_sb3.py --fetch --no-testnet --symbol BTC/USDT:USDT --timeframe 1h \\
        --limit 8000 --window 48 --timesteps 200_000 --out artifacts/rl_ppo

Live: set ``RL_MODEL_PATH`` to ``--out`` path (SB3 zip), ``RL_WINDOW`` = ``--window``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def _repo_src_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _synthetic_closes(n: int, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.002, size=n)
    return (100_000.0 * np.exp(np.cumsum(r))).astype(np.float64)


def _load_closes(args: argparse.Namespace) -> np.ndarray:
    if args.csv is not None:
        _repo_src_on_path()
        from binance_auto_ai.backtest.data import load_ohlcv_csv

        rows = load_ohlcv_csv(args.csv)
        if len(rows) < args.window + args.episode_len + 20:
            raise SystemExit("CSV too short for window + episode_len")
        return np.array([float(r[4]) for r in rows], dtype=np.float64)

    if args.fetch:
        _repo_src_on_path()
        from binance_auto_ai.backtest.data import fetch_ohlcv_ccxt_paginated

        rows = fetch_ohlcv_ccxt_paginated(
            symbol=args.symbol,
            timeframe=args.timeframe,
            max_bars=args.limit,
            testnet=not args.no_testnet,
            page_size=args.page_size,
            max_requests=args.max_requests,
        )
        print(
            f"loaded {len(rows)} bars paginated {args.symbol} {args.timeframe}",
        )
        if len(rows) < args.window + args.episode_len + 20:
            raise SystemExit("fetch too short")
        return np.array([float(r[4]) for r in rows], dtype=np.float64)

    return _synthetic_closes(args.n_bars)


def _parse_arch(s: str) -> list[int]:
    parts = [int(x.strip()) for x in s.split(",") if x.strip()]
    if not parts:
        raise ValueError("empty net arch")
    return parts


def main() -> None:
    p = argparse.ArgumentParser(description="Train SB3 PPO on FuturesPerpBarEnv → zip for rl_sb3.")
    data = p.add_mutually_exclusive_group()
    data.add_argument("--csv", type=Path)
    data.add_argument("--fetch", action="store_true")
    p.add_argument("--n-bars", type=int, default=12_000, help="Synthetic length if no csv/fetch")
    p.add_argument("--symbol", default="BTC/USDT:USDT")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--limit", type=int, default=8000)
    p.add_argument("--no-testnet", action="store_true")
    p.add_argument("--page-size", type=int, default=1500)
    p.add_argument("--max-requests", type=int, default=500)

    p.add_argument("--window", type=int, default=32, help="Must match RL_WINDOW live")
    p.add_argument("--reward", choices=("pnl", "pnl_cost", "risk_adjusted"), default="pnl_cost")
    p.add_argument("--trans-cost", type=float, default=5e-5, help="Turnover penalty per |Δpos| (log-ret scale)")
    p.add_argument("--episode-len", type=int, default=256)
    p.add_argument("--drawdown-penalty", type=float, default=0.5, help="risk_adjusted mode")

    p.add_argument("--algo", choices=("ppo",), default="ppo")
    p.add_argument("--timesteps", type=int, default=200_000)
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--n-steps", type=int, default=2048)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--gae-lambda", type=float, default=0.95)
    p.add_argument("--clip-range", type=float, default=0.2)
    p.add_argument("--ent-coef", type=float, default=0.0)
    p.add_argument("--net-arch", type=str, default="64,64", help="Comma MLP widths for pi/vf")

    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, default=Path("artifacts/rl_ppo"))
    args = p.parse_args()

    if not args.csv and not args.fetch:
        print("using synthetic prices (--n-bars); use --csv or --fetch for market data")

    try:
        from gymnasium import Env
        from stable_baselines3 import PPO
        from stable_baselines3.common.vec_env import DummyVecEnv
    except ImportError as e:
        raise SystemExit(
            'Need RL deps: pip install -e ".[rl]"  (stable-baselines3, gymnasium)',
        ) from e

    _repo_src_on_path()
    from binance_auto_ai.rl.futures_perp_env import FuturesPerpBarEnv

    closes = _load_closes(args)
    arch = _parse_arch(args.net_arch)

    def make_env() -> Env:
        return FuturesPerpBarEnv(
            closes,
            args.window,
            reward=args.reward,
            trans_cost=args.trans_cost,
            episode_len=args.episode_len,
            random_start=True,
            drawdown_penalty=args.drawdown_penalty,
        )

    vec = DummyVecEnv([make_env])
    model = PPO(
        "MlpPolicy",
        vec,
        learning_rate=args.learning_rate,
        n_steps=args.n_steps,
        batch_size=args.batch_size,
        gamma=args.gamma,
        gae_lambda=args.gae_lambda,
        clip_range=args.clip_range,
        ent_coef=args.ent_coef,
        seed=args.seed,
        verbose=1,
        policy_kwargs={"net_arch": arch},
    )
    model.learn(total_timesteps=args.timesteps)
    out_path = args.out
    if out_path.suffix.lower() != ".zip":
        out_path = out_path.with_suffix(".zip")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base = out_path.with_suffix("")
    model.save(str(base))
    print(f"saved SB3 model {base}.zip")


if __name__ == "__main__":
    main()
