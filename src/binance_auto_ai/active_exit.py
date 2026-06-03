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

from binance_auto_ai.coinglass_derivatives import CoinGlassMarketContext, derivatives_exit_reason
from binance_auto_ai.config import Settings
from binance_auto_ai.exchange_env import effective_leverage
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
        leverage: float = 1.0,
        cg_oi_change_pct: float | None = None,
        cg_funding_rate: float | None = None,
        cg_market: CoinGlassMarketContext | None = None,
        now_ts: float | None = None,
    ) -> ExitDecision:
        """更新该仓状态并判断是否触发离场。side 为空（平仓）时清除状态并返回不离场。

        ``leverage`` 用于把价格变动 % 换算为 **回报率 ROE = 价格变动% × 杠杆 = 收益/保证金**，
        供 ``EXIT_*_ROE_PCT`` 判断（如 ROE≥100 表示浮盈达到该仓保证金的 100%）。
        """
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

        lev = leverage if leverage and leverage > 0 else 1.0
        roe = pnl * lev

        sl = settings.exit_stop_loss_pct
        if sl > 0.0 and pnl <= -sl:
            return ExitDecision(True, f"stop_loss pnl={pnl:.2f}% <= -{sl:.2f}%")

        sl_roe = settings.exit_stop_loss_roe_pct
        if sl_roe > 0.0 and roe <= -sl_roe:
            return ExitDecision(True, f"stop_loss_roe roe={roe:.1f}% (pnl={pnl:.2f}%×{lev:.0f}) <= -{sl_roe:.1f}%")

        adverse_funding = settings.exit_cg_adverse_funding
        if adverse_funding > 0.0 and cg_funding_rate is not None:
            if side == "long" and cg_funding_rate >= adverse_funding:
                return ExitDecision(True, f"cg_adverse_funding long funding={cg_funding_rate:+.4f} >= {adverse_funding:.4f}")
            if side == "short" and cg_funding_rate <= -adverse_funding:
                return ExitDecision(True, f"cg_adverse_funding short funding={cg_funding_rate:+.4f} <= -{adverse_funding:.4f}")

        tp = settings.exit_take_profit_pct
        if tp > 0.0 and pnl >= tp:
            return ExitDecision(True, f"take_profit pnl={pnl:.2f}% >= {tp:.2f}%")

        tp_roe = settings.exit_take_profit_roe_pct
        if tp_roe > 0.0 and roe >= tp_roe:
            return ExitDecision(True, f"take_profit_roe roe={roe:.1f}% (pnl={pnl:.2f}%×{lev:.0f}) >= {tp_roe:.1f}%")

        trail = settings.exit_trailing_pct
        if trail > 0.0 and st.peak_pnl_pct >= trail and (st.peak_pnl_pct - pnl) >= trail:
            return ExitDecision(
                True,
                f"trailing peak={st.peak_pnl_pct:.2f}% drop={st.peak_pnl_pct - pnl:.2f}% >= {trail:.2f}%",
            )

        oi_drop = settings.exit_cg_oi_drop_pct
        if oi_drop > 0.0 and cg_oi_change_pct is not None and pnl >= 0.0 and cg_oi_change_pct <= -oi_drop:
            return ExitDecision(
                True,
                f"cg_oi_drop oi_change={cg_oi_change_pct:+.2f}% <= -{oi_drop:.2f}% (pnl={pnl:.2f}%≥0, 趋势衰竭落袋)",
            )

        cg_reason = derivatives_exit_reason(side, mark=mark, settings=settings, ctx=cg_market)
        if cg_reason:
            return ExitDecision(True, cg_reason)

        max_hold = settings.exit_max_hold_minutes
        if max_hold > 0.0:
            held_min = (now - st.first_ts) / 60.0
            if held_min >= max_hold:
                return ExitDecision(True, f"max_hold {held_min:.1f}min >= {max_hold:.1f}min")

        return ExitDecision(False, f"hold pnl={pnl:.2f}% peak={st.peak_pnl_pct:.2f}%")


def _coinglass_coin_metrics(settings: Settings, symbol: str, coinglass: object | None) -> tuple[float | None, float | None]:
    """返回该币的 (聚合OI变化%, 聚合资金费率)；未启用/取不到 → (None, None)。"""
    if coinglass is None or not settings.coinglass_exit_enabled():
        return None, None
    try:
        metrics = coinglass.coin_metrics()  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - CoinGlass 异常不影响价格类止损
        logger.debug("active exit: coinglass coin_metrics failed for %s (%s)", symbol, e)
        return None, None
    base = symbol.split("/")[0].upper()
    row = metrics.get(base) if isinstance(metrics, dict) else None
    if not isinstance(row, dict):
        return None, None
    return row.get("oi_change_pct"), row.get("funding_rate")


def _coinglass_market_context(
    settings: Settings,
    symbol: str,
    coinglass: object | None,
    *,
    mark: float,
) -> CoinGlassMarketContext | None:
    if coinglass is None or not settings.coinglass_derivatives_exit_enabled():
        return None
    try:
        return coinglass.market_context(symbol, mark_price=mark)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        logger.debug("active exit: coinglass market_context failed for %s (%s)", symbol, e)
        return None


def held_exit_signal(
    ex: ccxt.binanceusdm,
    settings: Settings,
    symbol: str,
    tracker: ExitTracker,
    coinglass: object | None = None,
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
    lev = 1.0
    if settings.exit_take_profit_roe_pct > 0.0 or settings.exit_stop_loss_roe_pct > 0.0:
        try:
            lev = effective_leverage(ex, settings, symbol)
        except Exception as e:  # noqa: BLE001
            logger.debug("active exit: leverage lookup failed for %s (%s); using 1x", symbol, e)
            lev = settings.leverage
    cg_oi_change_pct, cg_funding_rate = _coinglass_coin_metrics(settings, symbol, coinglass)
    cg_market = _coinglass_market_context(settings, symbol, coinglass, mark=mark)
    decision = tracker.update_and_check(
        symbol,
        side=entry.side,
        entry_price=entry.entry_price,
        mark=mark,
        settings=settings,
        leverage=lev,
        cg_oi_change_pct=cg_oi_change_pct,
        cg_funding_rate=cg_funding_rate,
        cg_market=cg_market,
    )
    if not decision.should_exit:
        return None
    return LLMSignal(
        action=Action.FLAT,
        size_pct=100.0,
        confidence=1.0,
        reason=f"active_exit: {decision.reason}",
    )
