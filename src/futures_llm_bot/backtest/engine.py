"""Vector-bar backtest with spot-style signed position and fee on notional."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from futures_llm_bot.schemas import Action, LLMSignal


class Strategy(Protocol):
    def reset(self) -> None: ...
    def on_bar(self, i: int, ohlcv: list[list[float]]) -> LLMSignal: ...


@dataclass
class Trade:
    bar_index: int
    price: float
    delta_contracts: float
    fee_usdt: float
    reason: str


@dataclass
class BacktestResult:
    """Simplified linear-perp approximation: equity = cash + position * close."""

    initial_cash_usdt: float
    max_notional_usdt: float
    fee_rate: float
    equity_curve: list[float] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    final_cash_usdt: float = 0.0
    final_position_contracts: float = 0.0

    @property
    def total_return_pct(self) -> float:
        if not self.equity_curve or self.initial_cash_usdt <= 0:
            return 0.0
        return (self.equity_curve[-1] / self.initial_cash_usdt - 1.0) * 100.0

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for x in self.equity_curve:
            peak = max(peak, x)
            if peak > 0:
                dd = (peak - x) / peak * 100.0
                max_dd = max(max_dd, dd)
        return max_dd


def _target_contracts(signal: LLMSignal, close: float, max_notional: float) -> float | None:
    """Return signed target size in base (e.g. BTC). ``None`` means **HOLD** (no change)."""
    if signal.action == Action.HOLD:
        return None
    if signal.action == Action.FLAT:
        return 0.0
    if close <= 0:
        return 0.0
    notional = max_notional * (signal.size_pct / 100.0)
    if notional <= 0:
        return 0.0
    magnitude = notional / close
    if signal.action == Action.LONG:
        return magnitude
    if signal.action == Action.SHORT:
        return -magnitude
    return 0.0


def run_backtest(
    ohlcv: list[list[float]],
    strategy: Strategy,
    *,
    initial_cash_usdt: float = 10_000.0,
    max_notional_usdt: float = 1_000.0,
    fee_bps: float = 4.0,
) -> BacktestResult:
    """Walk closed bars; execute at bar **close**; fee = ``fee_bps`` per 10_000 on traded notional.

    Position is **signed base size** (e.g. BTC); equity = ``cash + position * close`` (common linear-perp teaching model).
    """
    fee_rate = fee_bps / 10_000.0
    strategy.reset()
    cash = float(initial_cash_usdt)
    position = 0.0
    equity_curve: list[float] = []
    trades: list[Trade] = []

    for i in range(len(ohlcv)):
        close = float(ohlcv[i][4])
        sig = strategy.on_bar(i, ohlcv[: i + 1])
        tgt = _target_contracts(sig, close, max_notional_usdt)
        if tgt is None:
            equity_curve.append(cash + position * close)
            continue

        delta = tgt - position
        if abs(delta) < 1e-18:
            equity_curve.append(cash + position * close)
            continue

        notional = abs(delta * close)
        fee = notional * fee_rate
        cash -= delta * close + fee
        position = tgt
        trades.append(Trade(bar_index=i, price=close, delta_contracts=delta, fee_usdt=fee, reason=sig.reason[:80]))
        equity_curve.append(cash + position * close)

    return BacktestResult(
        initial_cash_usdt=initial_cash_usdt,
        max_notional_usdt=max_notional_usdt,
        fee_rate=fee_rate,
        equity_curve=equity_curve,
        trades=trades,
        final_cash_usdt=cash,
        final_position_contracts=position,
    )
