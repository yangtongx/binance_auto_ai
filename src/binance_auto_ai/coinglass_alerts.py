"""CoinGlass 链上/流向 Telegram 告警（只通知，不下单）。

1. 现货净流出（netflow-list）：24h 净流低于阈值 → 卖盘占优
2. 交易所储备增加（exchange/balance/list）：24h 储备增幅超阈值 → 潜在卖压
3. 大额链上转账（whale-transfer）：新出现的大额转账 → 关注是否流入交易所
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from binance_auto_ai.config import Settings
from binance_auto_ai.constants import NET_POSITION_EPS_CONTRACTS
from binance_auto_ai.telegram_format import SEPARATOR
from binance_auto_ai.telegram_notify import notify_coinglass_alert, telegram_configured

if TYPE_CHECKING:
    from binance_auto_ai.coinglass import CoinglassClient

logger = logging.getLogger(__name__)

_EXCHANGE_HINTS = (
    "binance",
    "okx",
    "okex",
    "coinbase",
    "kraken",
    "bybit",
    "bitfinex",
    "huobi",
    "htx",
    "kucoin",
    "gate",
    "exchange",
)


def coin_from_symbol(symbol: str) -> str:
    return symbol.split("/")[0].upper()


def _fmt_usd(v: float) -> str:
    av = abs(v)
    if av >= 1_000_000_000:
        return f"${av / 1_000_000_000:.2f}B"
    if av >= 1_000_000:
        return f"${av / 1_000_000:.2f}M"
    if av >= 1_000:
        return f"${av / 1_000:.1f}K"
    return f"${av:.0f}"


def _looks_like_exchange(label: str) -> bool:
    low = label.lower()
    return any(h in low for h in _EXCHANGE_HINTS)


def _cooldown_ok(state: dict[str, float], key: str, cooldown_sec: float, now: float) -> bool:
    last = state.get(key, 0.0)
    return (now - last) >= cooldown_sec


def _mark_sent(state: dict[str, float], key: str, now: float) -> None:
    state[key] = now


def resolve_watch_coins(
    *,
    candidate_symbols: list[str] | None,
    held_symbols: list[str] | None,
    extra: str,
) -> list[str]:
    coins: set[str] = set()
    for sym in candidate_symbols or []:
        if sym.strip():
            coins.add(coin_from_symbol(sym))
    for sym in held_symbols or []:
        if sym.strip():
            coins.add(coin_from_symbol(sym))
    for part in extra.split(","):
        c = part.strip().upper()
        if c:
            coins.add(c)
    return sorted(coins)


def list_held_symbols(ex, *, dry_run: bool) -> list[str]:  # noqa: ANN001
    """当前有持仓的合约 symbol 列表。"""
    if dry_run:
        return []
    try:
        rows = list(ex.fetch_positions())
    except Exception as e:  # noqa: BLE001
        logger.debug("list_held_symbols failed: %s", e)
        return []
    out: list[str] = []
    for p in rows:
        sym = str(p.get("symbol") or "")
        if not sym:
            continue
        try:
            c = float(p.get("contracts") or 0)
        except (TypeError, ValueError):
            continue
        if abs(c) >= NET_POSITION_EPS_CONTRACTS:
            out.append(sym)
    return out


class CoinglassAlertWatcher:
    """按间隔轮询 CoinGlass 并发送 Telegram 告警。"""

    def __init__(self) -> None:
        self._last_run_monotonic = 0.0
        self._cooldown_state: dict[str, float] = {}
        self._seen_whale_tx: set[str] = set()

    def maybe_check(
        self,
        settings: Settings,
        coinglass: CoinglassClient | None,
        *,
        candidate_symbols: list[str] | None = None,
        held_symbols: list[str] | None = None,
    ) -> None:
        if not settings.coinglass_alert_enabled() or coinglass is None:
            return
        if not telegram_configured(settings):
            return
        now = time.monotonic()
        interval = float(settings.coinglass_alert_interval_sec)
        if self._last_run_monotonic and (now - self._last_run_monotonic) < interval:
            return
        self._last_run_monotonic = now

        coins = resolve_watch_coins(
            candidate_symbols=candidate_symbols,
            held_symbols=held_symbols,
            extra=settings.coinglass_alert_extra_coins,
        )
        if not coins:
            return

        cooldown = float(settings.coinglass_alert_cooldown_sec)
        netflow_thr = float(settings.coinglass_alert_netflow_usd)
        bal_thr = float(settings.coinglass_alert_exchange_balance_pct_1d)
        whale_thr = float(settings.coinglass_alert_whale_usd)

        if netflow_thr > 0:
            self._check_netflow(settings, coinglass, coins, netflow_thr, cooldown, now)
        if bal_thr > 0:
            self._check_exchange_balance(settings, coinglass, coins, bal_thr, cooldown, now)
        if whale_thr > 0:
            self._check_whale_transfers(settings, coinglass, coins, whale_thr, interval, now)

    def _check_netflow(
        self,
        settings: Settings,
        coinglass: CoinglassClient,
        coins: list[str],
        threshold_usd: float,
        cooldown_sec: float,
        now: float,
    ) -> None:
        try:
            netflow = coinglass.spot_netflow()
        except Exception as e:  # noqa: BLE001
            logger.debug("coinglass alert netflow failed: %s", e)
            return
        for coin in coins:
            row = netflow.get(coin)
            if not row:
                continue
            nf24 = row.get("net_flow_24h_usd")
            if nf24 is None or nf24 >= -threshold_usd:
                continue
            key = f"netflow:{coin}"
            if not _cooldown_ok(self._cooldown_state, key, cooldown_sec, now):
                continue
            nf1 = row.get("net_flow_1h_usd")
            lines = [
                f"📉 现货净流出 · {coin}",
                SEPARATOR,
                f"24h 净流  -{_fmt_usd(nf24)}",
            ]
            if nf1 is not None and nf1 < 0:
                lines.append(f"1h 净流   -{_fmt_usd(nf1)}")
            lines.append("提示  现货主动卖盘占优，注意潜在出货风险")
            notify_coinglass_alert(settings, "\n".join(lines))
            _mark_sent(self._cooldown_state, key, now)
            logger.info("coinglass alert: netflow %s 24h=%.0f", coin, nf24)

    def _check_exchange_balance(
        self,
        settings: Settings,
        coinglass: CoinglassClient,
        coins: list[str],
        threshold_pct: float,
        cooldown_sec: float,
        now: float,
    ) -> None:
        for coin in coins:
            try:
                rows = coinglass.exchange_balance(coin)
            except Exception as e:  # noqa: BLE001
                logger.debug("coinglass alert exchange balance failed for %s: %s", coin, e)
                continue
            hits = [
                r
                for r in rows
                if r.get("balance_change_percent_1d") is not None
                and float(r["balance_change_percent_1d"]) >= threshold_pct  # type: ignore[arg-type]
            ]
            if not hits:
                continue
            hits.sort(key=lambda r: float(r["balance_change_percent_1d"]), reverse=True)  # type: ignore[arg-type]
            top = hits[0]
            key = f"balance:{coin}"
            if not _cooldown_ok(self._cooldown_state, key, cooldown_sec, now):
                continue
            detail_lines = []
            for r in hits[:4]:
                detail_lines.append(
                    f"{r['exchange_name']}  +{float(r['balance_change_percent_1d']):.2f}% (24h)"  # type: ignore[arg-type]
                )
            lines = [
                f"🏦 交易所储备增加 · {coin}",
                SEPARATOR,
                *detail_lines,
                f"最大增幅 +{float(top['balance_change_percent_1d']):.2f}%",  # type: ignore[arg-type]
                "提示  币流入交易所，潜在卖压上升",
            ]
            notify_coinglass_alert(settings, "\n".join(lines))
            _mark_sent(self._cooldown_state, key, now)
            logger.info("coinglass alert: exchange balance %s max=%.2f%%", coin, top["balance_change_percent_1d"])

    def _check_whale_transfers(
        self,
        settings: Settings,
        coinglass: CoinglassClient,
        coins: list[str],
        threshold_usd: float,
        interval_sec: float,
        now: float,
    ) -> None:
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - int(max(interval_sec * 2, 300) * 1000)
        for coin in coins:
            try:
                transfers = coinglass.whale_transfers(coin, start_ms=start_ms, end_ms=end_ms)
            except Exception as e:  # noqa: BLE001
                logger.debug("coinglass alert whale failed for %s: %s", coin, e)
                continue
            for tx in transfers:
                tx_hash = str(tx.get("transaction_hash", ""))
                if not tx_hash or tx_hash in self._seen_whale_tx:
                    continue
                amount = tx.get("amount_usd")
                if amount is None or float(amount) < threshold_usd:  # type: ignore[arg-type]
                    continue
                self._seen_whale_tx.add(tx_hash)
                if len(self._seen_whale_tx) > 2000:
                    self._seen_whale_tx = set(list(self._seen_whale_tx)[-1000:])

                frm = str(tx.get("from") or "—")
                to = str(tx.get("to") or "—")
                asset = str(tx.get("asset_symbol") or coin)
                chain = str(tx.get("blockchain") or "—")
                ts = tx.get("block_timestamp")
                ts_line = ""
                if isinstance(ts, int) and ts > 0:
                    ts_line = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

                hint = "大额链上转账"
                if _looks_like_exchange(to):
                    hint = "大额资金转入交易所，注意潜在卖压"
                elif _looks_like_exchange(frm):
                    hint = "大额资金从交易所转出"

                lines = [
                    f"🐋 链上大户转账 · {coin}",
                    SEPARATOR,
                    f"金额  {_fmt_usd(float(amount))} {asset}",  # type: ignore[arg-type]
                    f"链    {chain}",
                    f"从    {frm}",
                    f"至    {to}",
                ]
                if ts_line:
                    lines.append(f"时间  {ts_line}")
                lines.append(f"提示  {hint}")
                notify_coinglass_alert(settings, "\n".join(lines))
                logger.info("coinglass alert: whale %s %s usd=%.0f", coin, tx_hash[:16], float(amount))  # type: ignore[arg-type]
