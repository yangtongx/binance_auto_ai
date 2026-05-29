#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""Example: train a 3-class model (hold/long/short) and export TorchScript for ``STRATEGY_NAME=ml``.

**You do not need your own trade logs.** Use either:

- **Synthetic** random walk (default): sanity-check pipeline only.
- **``--csv``**: OHLCV file in the same shape as ``futures-llm-backtest`` (timestamp, o, h, l, c, v).
- **``--fetch``**: download public **Binance USDM** history via CCXT (no API key for read-only klines).

Labels in this script are still **heuristic** (next-bar log-return vs a neutral band ``--eps``).
They are **not** oracle trade labels — replace with your own objective if you go live.

Usage (from repo root; ``pip install -e ".[ml-torch]"`` first)::

    # 合成数据（流水线自检）
    python examples/train_ml_torch.py --arch lstm --window 32 --epochs 40 --out artifacts/ml_lstm.pt

    # 真实行情（分页公开 K 线 — 无需 API 密钥）
    python examples/train_ml_torch.py --fetch --no-testnet --symbol BTC/USDT:USDT --timeframe 4h --limit 20000 \\
        --page-size 1500 --arch lstm --window 48 --epochs 40 --out artifacts/ml_latest.pt

    # 与 ``futures-llm-backtest`` 兼容导出的 CSV
    python examples/train_ml_torch.py --csv data/btc_1h.csv --arch mlp --window 32 --out artifacts/ml_csv.pt

Live: ``STRATEGY_NAME=ml``, ``ML_BACKEND=torch``, ``ML_TORCH_ARCH`` matching ``--arch``,
``STRATEGY_ML_WINDOW`` = ``--window``, ``ML_MODEL_PATH`` = output ``.pt``.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np


def _repo_src_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _synthetic_series(n: int, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.002, size=n)
    c = 100_000.0 * np.exp(np.cumsum(r))
    return c.astype(np.float64)


def _log_returns(closes: np.ndarray) -> np.ndarray:
    c = np.clip(closes.astype(np.float64), 1e-9, None)
    return np.diff(np.log(c))


def _labels_from_future_ret(closes: np.ndarray, eps: float) -> np.ndarray:
    """``full_lr[i]`` = log-return from bar i to i+1; length len(closes)-1."""
    lr = _log_returns(closes)
    y = np.zeros(len(lr), dtype=np.int64)
    for i in range(len(lr)):
        nxt = lr[i]
        if nxt > eps:
            y[i] = 1
        elif nxt < -eps:
            y[i] = 2
        else:
            y[i] = 0
    return y


def _load_closes(args: argparse.Namespace) -> np.ndarray:
    if args.csv is not None:
        _repo_src_on_path()
        from futures_llm_bot.backtest.data import load_ohlcv_csv

        rows = load_ohlcv_csv(args.csv)
        if len(rows) < args.window + 10:
            raise SystemExit(f"CSV too short: {len(rows)} rows")
        return np.array([float(r[4]) for r in rows], dtype=np.float64)

    if args.fetch:
        _repo_src_on_path()
        from futures_llm_bot.backtest.data import fetch_ohlcv_ccxt_paginated

        rows = fetch_ohlcv_ccxt_paginated(
            symbol=args.symbol,
            timeframe=args.timeframe,
            max_bars=args.limit,
            testnet=not args.no_testnet,
            page_size=args.page_size,
            max_requests=args.max_requests,
        )
        if len(rows) < args.window + 10:
            raise SystemExit(f"fetch too short: {len(rows)} rows (want >= window+10)")
        print(
            f"loaded {len(rows)} bars (paginated, page_size={args.page_size}) "
            f"{args.symbol} {args.timeframe}",
        )
        return np.array([float(r[4]) for r in rows], dtype=np.float64)

    return _synthetic_series(args.n_bars)


def main() -> None:
    p = argparse.ArgumentParser(description="Train toy ML model → TorchScript for futures-llm-bot.")
    p.add_argument("--arch", choices=("mlp", "lstm", "transformer"), default="lstm")
    p.add_argument("--window", type=int, default=32, help="Per live STRATEGY_ML_WINDOW (≥8)")
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--n-bars", type=int, default=8000, help="Synthetic bars (when not --csv/--fetch)")
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--eps", type=float, default=5e-5, help="Neutral band on next log-return")
    p.add_argument("--out", type=Path, default=Path("artifacts/ml_model.pt"))
    p.add_argument("--csv", type=Path, help="OHLCV CSV like backtest (ts,o,h,l,c,v)")
    p.add_argument("--fetch", action="store_true", help="Download OHLCV via CCXT (Binance USDM)")
    p.add_argument("--symbol", default="BTC/USDT:USDT", help="With --fetch")
    p.add_argument("--timeframe", default="1h", help="With --fetch")
    p.add_argument("--limit", type=int, default=5000, help="Total bars to fetch (paginated)")
    p.add_argument(
        "--page-size",
        type=int,
        default=1500,
        help="Max bars per CCXT call (Binance cap ~1500)",
    )
    p.add_argument(
        "--max-requests",
        type=int,
        default=500,
        help="Safety cap on pagination rounds",
    )
    p.add_argument(
        "--no-testnet",
        action="store_true",
        help="With --fetch: use Binance **mainnet** public klines (recommended for research volume)",
)
    args = p.parse_args()

    if args.csv is not None and args.fetch:
        raise SystemExit("use either --csv or --fetch, not both")

    try:
        import torch
        import torch.nn as nn
    except ImportError as e:
        raise SystemExit('Need PyTorch: pip install -e ".[ml-torch]"') from e

    closes = _load_closes(args)
    y_bar = _labels_from_future_ret(closes, args.eps)
    feat_len = args.window - 1

    xs: list[np.ndarray] = []
    ys: list[int] = []
    for t in range(args.window - 1, len(closes) - 1):
        w = closes[t - args.window + 1 : t + 1]
        lr_feat = _log_returns(w)
        if lr_feat.size != feat_len:
            continue
        xs.append(lr_feat)
        ys.append(int(y_bar[t]))

    if len(xs) < 50:
        raise SystemExit("not enough samples; increase --n-bars / --limit or lower --window")

    X = np.stack(xs, axis=0).astype(np.float32)
    y = np.array(ys, dtype=np.int64)
    n = X.shape[0]
    perm = np.random.default_rng(0).permutation(n)
    X, y = X[perm], y[perm]
    split = int(n * 0.85)
    Xt, Xv = X[:split], X[split:]
    yt, yv = y[:split], y[split:]

    class Mlp(nn.Module):
        def __init__(self, fin: int) -> None:
            super().__init__()
            self.net = nn.Sequential(nn.Linear(fin, 64), nn.ReLU(), nn.Linear(64, 3))

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.net(x)

    class LstmCls(nn.Module):
        def __init__(self, fin: int, hidden: int = 48) -> None:
            super().__init__()
            self.lstm = nn.LSTM(1, hidden, batch_first=True)
            self.fc = nn.Linear(hidden, 3)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            y, _ = self.lstm(x)
            return self.fc(y[:, -1, :])

    class MiniTransformer(nn.Module):
        def __init__(self, d_model: int = 32, nhead: int = 4, nlayers: int = 2) -> None:
            super().__init__()
            self.proj = nn.Linear(1, d_model)
            layer = nn.TransformerEncoderLayer(
                d_model, nhead, dim_feedforward=96, dropout=0.0, batch_first=True
            )
            self.enc = nn.TransformerEncoder(layer, nlayers)
            self.fc = nn.Linear(d_model, 3)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            h = self.enc(self.proj(x))
            return self.fc(h[:, -1, :])

    if args.arch == "mlp":
        model: nn.Module = Mlp(feat_len)
        ex = torch.zeros(1, feat_len, dtype=torch.float32)
    elif args.arch == "lstm":
        model = LstmCls(feat_len)
        ex = torch.zeros(1, feat_len, 1, dtype=torch.float32)
    else:
        model = MiniTransformer()
        ex = torch.zeros(1, feat_len, 1, dtype=torch.float32)

    device = torch.device("cpu")
    model.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.CrossEntropyLoss()
    Xt_t = torch.from_numpy(Xt).to(device)
    yt_t = torch.from_numpy(yt).to(device)
    if args.arch != "mlp":
        Xt_t = Xt_t.unsqueeze(-1)

    bs = 256
    for epoch in range(args.epochs):
        model.train()
        total = 0.0
        steps = max(1, math.ceil(split / bs))
        for s in range(steps):
            sl = slice(s * bs, (s + 1) * bs)
            xb, yb = Xt_t[sl], yt_t[sl]
            if xb.size(0) == 0:
                continue
            opt.zero_grad()
            logits = model(xb)
            loss = loss_fn(logits, yb)
            loss.backward()
            opt.step()
            total += float(loss.item())
        if (epoch + 1) % max(1, args.epochs // 5) == 0:
            model.eval()
            with torch.no_grad():
                xv = torch.from_numpy(Xv).to(device)
                if args.arch != "mlp":
                    xv = xv.unsqueeze(-1)
                pred = model(xv).argmax(dim=-1).cpu().numpy()
                acc = float((pred == yv).mean()) if len(yv) else 0.0
            print(f"epoch {epoch+1}/{args.epochs} loss={total/steps:.4f} val_acc={acc:.3f}")

    model.eval()
    traced = torch.jit.trace(model.cpu(), ex.cpu())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    traced.save(str(args.out))
    print(f"saved TorchScript ({args.arch}) → {args.out.resolve()}")
    print(f"live env: STRATEGY_NAME=ml ML_BACKEND=torch ML_TORCH_ARCH={args.arch} STRATEGY_ML_WINDOW={args.window}")


if __name__ == "__main__":
    main()
