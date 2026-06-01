"""Tests for active-exit rules (stop-loss / take-profit / trailing / time-stop)."""

from __future__ import annotations

from binance_auto_ai.active_exit import ExitTracker, held_exit_signal, pnl_pct_from_entry
from binance_auto_ai.config import Settings
from binance_auto_ai.positions import fetch_position_entry
from binance_auto_ai.schemas import Action


def _settings(**kw: object) -> Settings:
    base = dict(
        exit_stop_loss_pct=0.0,
        exit_take_profit_pct=0.0,
        exit_trailing_pct=0.0,
        exit_max_hold_minutes=0.0,
        exit_take_profit_roe_pct=0.0,
        exit_stop_loss_roe_pct=0.0,
        exit_cg_oi_drop_pct=0.0,
        exit_cg_adverse_funding=0.0,
        leverage=1.0,
        leverage_mode="fixed",
        dry_run=False,
    )
    base.update(kw)
    return Settings.model_construct(**base)


def test_pnl_pct_from_entry() -> None:
    assert pnl_pct_from_entry("long", entry_price=100.0, mark=102.0) == 2.0
    assert pnl_pct_from_entry("short", entry_price=100.0, mark=98.0) == 2.0
    assert pnl_pct_from_entry("long", entry_price=100.0, mark=95.0) == -5.0
    assert pnl_pct_from_entry("", entry_price=100.0, mark=100.0) is None
    assert pnl_pct_from_entry("long", entry_price=0.0, mark=100.0) is None


def test_stop_loss_triggers() -> None:
    s = _settings(exit_stop_loss_pct=2.0)
    t = ExitTracker()
    assert t.update_and_check("X", side="long", entry_price=100.0, mark=99.0, settings=s).should_exit is False
    assert t.update_and_check("X", side="long", entry_price=100.0, mark=98.0, settings=s).should_exit is True


def test_stop_loss_short_side() -> None:
    s = _settings(exit_stop_loss_pct=2.0)
    t = ExitTracker()
    # short loses when price rises
    assert t.update_and_check("X", side="short", entry_price=100.0, mark=102.5, settings=s).should_exit is True


def test_take_profit_triggers() -> None:
    s = _settings(exit_take_profit_pct=3.0)
    t = ExitTracker()
    assert t.update_and_check("X", side="long", entry_price=100.0, mark=102.0, settings=s).should_exit is False
    assert t.update_and_check("X", side="long", entry_price=100.0, mark=103.0, settings=s).should_exit is True


def test_trailing_arms_then_triggers_on_retrace() -> None:
    s = _settings(exit_trailing_pct=2.0)
    t = ExitTracker()
    # not armed yet (peak < 2%)
    assert t.update_and_check("X", side="long", entry_price=100.0, mark=100.0, settings=s).should_exit is False
    # peak rises to +5% (armed), no retrace yet
    assert t.update_and_check("X", side="long", entry_price=100.0, mark=105.0, settings=s).should_exit is False
    # retrace from peak 5% down to 3% => drop 2% >= 2% => exit
    assert t.update_and_check("X", side="long", entry_price=100.0, mark=103.0, settings=s).should_exit is True


def test_trailing_not_triggered_before_armed() -> None:
    s = _settings(exit_trailing_pct=5.0)
    t = ExitTracker()
    # peak only +1% then drop to -1%: not armed (peak < 5%) -> no trailing exit
    t.update_and_check("X", side="long", entry_price=100.0, mark=101.0, settings=s)
    assert t.update_and_check("X", side="long", entry_price=100.0, mark=99.0, settings=s).should_exit is False


def test_max_hold_time_stop() -> None:
    s = _settings(exit_max_hold_minutes=1.0)
    t = ExitTracker()
    assert t.update_and_check(
        "X", side="long", entry_price=100.0, mark=100.0, settings=s, now_ts=1000.0
    ).should_exit is False
    assert t.update_and_check(
        "X", side="long", entry_price=100.0, mark=100.0, settings=s, now_ts=1061.0
    ).should_exit is True


def test_take_profit_roe_triggers_at_full_margin() -> None:
    # ROE = price move % × leverage. With lev=50, +2% price = +100% ROE = profit equals margin.
    s = _settings(exit_take_profit_roe_pct=100.0)
    t = ExitTracker()
    assert t.update_and_check(
        "X", side="long", entry_price=100.0, mark=101.5, settings=s, leverage=50.0
    ).should_exit is False  # +1.5% × 50 = 75% ROE
    d = t.update_and_check("X", side="long", entry_price=100.0, mark=102.0, settings=s, leverage=50.0)
    assert d.should_exit is True  # +2% × 50 = 100% ROE
    assert "take_profit_roe" in d.reason


def test_stop_loss_roe_triggers() -> None:
    s = _settings(exit_stop_loss_roe_pct=80.0)
    t = ExitTracker()
    # short, price up 2% with lev 50 => -100% ROE <= -80% => exit
    assert t.update_and_check(
        "X", side="short", entry_price=100.0, mark=102.0, settings=s, leverage=50.0
    ).should_exit is True


def test_roe_disabled_when_zero() -> None:
    s = _settings(exit_take_profit_roe_pct=0.0, exit_stop_loss_roe_pct=0.0)
    t = ExitTracker()
    assert t.update_and_check(
        "X", side="long", entry_price=100.0, mark=130.0, settings=s, leverage=125.0
    ).should_exit is False


def test_cg_oi_drop_exit_only_when_in_profit() -> None:
    s = _settings(exit_cg_oi_drop_pct=15.0)
    t = ExitTracker()
    # in profit + OI collapsing -20% <= -15% -> exit
    d = t.update_and_check(
        "X", side="long", entry_price=100.0, mark=102.0, settings=s, cg_oi_change_pct=-20.0
    )
    assert d.should_exit is True
    assert "cg_oi_drop" in d.reason
    # at a loss -> OI-drop rule does not fire (price stop handles losses)
    t2 = ExitTracker()
    assert t2.update_and_check(
        "Y", side="long", entry_price=100.0, mark=98.0, settings=s, cg_oi_change_pct=-20.0
    ).should_exit is False
    # in profit but OI not dropping enough -> no exit
    t3 = ExitTracker()
    assert t3.update_and_check(
        "Z", side="long", entry_price=100.0, mark=102.0, settings=s, cg_oi_change_pct=-5.0
    ).should_exit is False


def test_cg_adverse_funding_guard() -> None:
    s = _settings(exit_cg_adverse_funding=0.05)
    t = ExitTracker()
    # long + funding very positive (crowded longs) -> exit
    assert t.update_and_check(
        "X", side="long", entry_price=100.0, mark=100.0, settings=s, cg_funding_rate=0.08
    ).should_exit is True
    # short + funding very negative -> exit
    t2 = ExitTracker()
    assert t2.update_and_check(
        "Y", side="short", entry_price=100.0, mark=100.0, settings=s, cg_funding_rate=-0.08
    ).should_exit is True
    # long + mildly positive funding -> no exit
    t3 = ExitTracker()
    assert t3.update_and_check(
        "Z", side="long", entry_price=100.0, mark=100.0, settings=s, cg_funding_rate=0.01
    ).should_exit is False


def test_cg_rules_inactive_without_data() -> None:
    s = _settings(exit_cg_oi_drop_pct=15.0, exit_cg_adverse_funding=0.05)
    t = ExitTracker()
    # no CoinGlass data passed -> rules skip, price stops still govern (none set here)
    assert t.update_and_check(
        "X", side="long", entry_price=100.0, mark=102.0, settings=s
    ).should_exit is False


def test_new_position_resets_timer_and_peak() -> None:
    s = _settings(exit_max_hold_minutes=1.0)
    t = ExitTracker()
    t.update_and_check("X", side="long", entry_price=100.0, mark=100.0, settings=s, now_ts=1000.0)
    # flip to short (new position) far in the future -> timer restarts, no time-stop
    assert t.update_and_check(
        "X", side="short", entry_price=100.0, mark=100.0, settings=s, now_ts=99999.0
    ).should_exit is False


def test_flat_forgets_state() -> None:
    s = _settings(exit_stop_loss_pct=2.0)
    t = ExitTracker()
    t.update_and_check("X", side="long", entry_price=100.0, mark=105.0, settings=s)
    d = t.update_and_check("X", side="", entry_price=0.0, mark=0.0, settings=s)
    assert d.should_exit is False
    assert "X" not in t._state


# --- position entry parsing + end-to-end held_exit_signal ---


class _FakeExitEx:
    def __init__(self, positions: list[dict], last: float) -> None:
        self._positions = positions
        self._last = last

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict]:
        return self._positions

    def fetch_ticker(self, symbol: str) -> dict:
        return {"last": self._last}


def test_fetch_position_entry_long() -> None:
    ex = _FakeExitEx(
        [{"symbol": "BTC/USDT:USDT", "side": "long", "contracts": 2.0, "entryPrice": 100.0}],
        last=100.0,
    )
    e = fetch_position_entry(ex, "BTC/USDT:USDT")  # type: ignore[arg-type]
    assert e.side == "long"
    assert e.entry_price == 100.0
    assert e.contracts == 2.0


def test_fetch_position_entry_flat() -> None:
    ex = _FakeExitEx([], last=100.0)
    e = fetch_position_entry(ex, "BTC/USDT:USDT")  # type: ignore[arg-type]
    assert e.side == ""


def test_held_exit_signal_stop_loss_flat() -> None:
    s = _settings(exit_stop_loss_pct=2.0)
    t = ExitTracker()
    ex = _FakeExitEx(
        [{"symbol": "BTC/USDT:USDT", "side": "long", "contracts": 1.0, "entryPrice": 100.0}],
        last=97.0,  # -3% on a long
    )
    sig = held_exit_signal(ex, s, "BTC/USDT:USDT", t)  # type: ignore[arg-type]
    assert sig is not None
    assert sig.action == Action.FLAT
    assert "active_exit" in sig.reason


def test_held_exit_signal_none_when_within_bounds() -> None:
    s = _settings(exit_stop_loss_pct=5.0, exit_take_profit_pct=5.0)
    t = ExitTracker()
    ex = _FakeExitEx(
        [{"symbol": "BTC/USDT:USDT", "side": "long", "contracts": 1.0, "entryPrice": 100.0}],
        last=101.0,
    )
    assert held_exit_signal(ex, s, "BTC/USDT:USDT", t) is None  # type: ignore[arg-type]
