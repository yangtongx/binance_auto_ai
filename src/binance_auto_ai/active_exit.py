"""主动离场：止损 / 止盈 / 移动止盈 / 持仓超时。

与策略信号无关，在每个 tick 优先判断是否强制平仓（输出 FLAT 信号）。
盈亏按**入场价的价格变动百分比**衡量（杠杆 L 下对权益影响≈pct×L）：
- long：pnl% = (mark - entry) / entry × 100
- short：pnl% = (entry - mark) / entry × 100

移动止盈与超时需要运行期状态（最高浮盈、首次见到该仓的时刻），由 :class:`ExitTracker`
按交易对在内存中维护；进程重启后会以再次见到该仓的时刻/价重新基准化（偏保守）。
止损/止盈只依赖交易所入场价，无需状态，重启后照常生效。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import ccxt

from binance_auto_ai.config import Settings
from binance_auto_ai.positions import fetch_position_entry, mark_last_usdt
from binance_auto_ai.schemas import Action, LLMSignal

logger = logging.getLogger(__name__)

# 判定「同一笔持仓」时入场价的相对容差
_ENTRY_REL_TOL = 1e-4


@dataclass
class ExitDecision:
    should_exit: bool
    reason: str


@dataclass
class _PosState:
    side: str
    entry_price: float
    first_ts: float
    peak_pnl_pct: float


def pnl_pct_from_entry(side: str, *, entry_price: float, mark: float) -> float | None:
    """相对入场价的价格变动百分比（有利为正）。无效输入返回 None。"""
    if entry_price <= 0 or mark <= 0:
        return None
    if side == "long":
        return (mark - entry_price) / entry_price * 100.0
    if side == "short":
        return (entry_price - mark) / entry_price * 100.0
    return None


class ExitTracker:
    """按交易对维护持仓的最高浮盈与首次见到时刻，供移动止盈/超时判断。"""

    def __init__(self) -> None:
        self._state: dict[str, _PosState] = {}

    def forget(self, symbol: str) -> None:
        self._state.pop(symbol, None)

    def _is_same_position(self, st: _PosState, *, side: str, entry_price: float) -> bool:
        if st.side != side or entry_price <= 0:
            return False
        return abs(st.entry_price - entry_price) <= max(entry_price * _ENTRY_REL_TOL, 1e-12)

    def update_and_check(
        self,
        symbol: str,
        *,
        side: str,
        entry_price: float,
        mark: float,
        settings: Settings,
        now_ts: float | None = None,
    ) -> ExitDecision:
        """更新该仓状态并判断是否触发离场。side 为空（平仓）时清除状态并返回不离场。"""
        now = time.time() if now_ts is None else now_ts
        pnl = pnl_pct_from_entry(side, entry_price=entry_price, mark=mark)
        if pnl is None:
            self.forget(symbol)
            return ExitDecision(False, "no open position")

        st = self._state.get(symbol)
        if st is None or not self._is_same_position(st, side=side, entry_price=entry_price):
            st = _PosState(side=side, entry_price=entry_price, first_ts=now, peak_pnl_pct=pnl)
            self._state[symbol] = st
        else:
            st.peak_pnl_pct = max(st.peak_pnl_pct, pnl)

        sl = settings.exit_stop_loss_pct
        if sl > 0.0 and pnl <= -sl:
            return ExitDecision(True, f"stop_loss pnl={pnl:.2f}% <= -{sl:.2f}%")

        tp = settings.exit_take_profit_pct
        if tp > 0.0 and pnl >= tp:
            return ExitDecision(True, f"take_profit pnl={pnl:.2f}% >= {tp:.2f}%")

        trail = settings.exit_trailing_pct
        if trail > 0.0 and st.peak_pnl_pct >= trail and (st.peak_pnl_pct - pnl) >= trail:
            return ExitDecision(
                True,
                f"trailing peak={st.peak_pnl_pct:.2f}% drop={st.peak_pnl_pct - pnl:.2f}% >= {trail:.2f}%",
            )

        max_hold = settings.exit_max_hold_minutes
        if max_hold > 0.0:
            held_min = (now - st.first_ts) / 60.0
            if held_min >= max_hold:
                return ExitDecision(True, f"max_hold {held_min:.1f}min >= {max_hold:.1f}min")

        return ExitDecision(False, f"hold pnl={pnl:.2f}% peak={st.peak_pnl_pct:.2f}%")


def held_exit_signal(
    ex: ccxt.binanceusdm,
    settings: Settings,
    symbol: str,
    tracker: ExitTracker,
) -> LLMSignal | None:
    """若该交易对持仓触发任一离场规则，返回一个 FLAT 信号；否则 None。"""
    try:
        entry = fetch_position_entry(ex, symbol, dry_run=settings.dry_run)
    except ccxt.BaseError as e:
        logger.debug("active exit: fetch_position_entry failed for %s (%s)", symbol, e)
        return None
    if entry.side not in ("long", "short") or entry.entry_price <= 0:
        tracker.forget(symbol)
        return None
    try:
        mark = mark_last_usdt(ex, symbol)
    except Exception as e:  # noqa: BLE001 - 行情异常不应触发误平
        logger.debug("active exit: mark price unavailable for %s (%s)", symbol, e)
        return None
    decision = tracker.update_and_check(
        symbol,
        side=entry.side,
        entry_price=entry.entry_price,
        mark=mark,
        settings=settings,
    )
    if not decision.should_exit:
        return None
    return LLMSignal(
        action=Action.FLAT,
        size_pct=100.0,
        confidence=1.0,
        reason=f"active_exit: {decision.reason}",
    )
