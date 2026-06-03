from __future__ import annotations

import numpy as np

from binance_auto_ai.backtest.indicators import atr_wilder_series, stochastic_cross_state
from binance_auto_ai.binance_kline_ws import reconnect_delay_sec
from binance_auto_ai.config import Settings
from binance_auto_ai.schemas import Action, LLMSignal
from binance_auto_ai.telegram_format import format_trade_message
from binance_auto_ai.telegram_notify import should_notify_trade_signal


def test_reconnect_delay_monotonic() -> None:
    d1 = reconnect_delay_sec(1, base_sec=1.0, max_sec=60.0, jitter_frac=0.0)
    d2 = reconnect_delay_sec(2, base_sec=1.0, max_sec=60.0, jitter_frac=0.0)
    assert d2 >= d1
    dcap = reconnect_delay_sec(99, base_sec=1.0, max_sec=10.0, jitter_frac=0.0)
    assert dcap == 10.0


def test_should_notify_trade_signal_modes() -> None:
    sig_hold = LLMSignal(action=Action.HOLD, size_pct=0.0, confidence=0.5, reason="wait")
    sig_long = LLMSignal(action=Action.LONG, size_pct=10.0, confidence=0.8, reason="go")
    s_all = Settings(telegram_notify_signals="all")
    s_dir = Settings(telegram_notify_signals="directional")
    s_off = Settings(telegram_notify_signals="off")
    assert should_notify_trade_signal(s_all, sig_hold) is True
    assert should_notify_trade_signal(s_dir, sig_hold) is False
    assert should_notify_trade_signal(s_dir, sig_long) is True
    assert should_notify_trade_signal(s_off, sig_long) is False


def test_notify_real_order_includes_mark_price(monkeypatch) -> None:
    sent: list[str] = []

    def _fake_send(_s: Settings, text: str, **_: object) -> None:
        sent.append(text)

    monkeypatch.setattr("binance_auto_ai.telegram_notify.send_telegram_message", _fake_send)
    s = Settings.model_construct(
        telegram_bot_token="t",
        telegram_chat_id="c",
        telegram_notify_orders=True,
        symbol="BTC/USDT:USDT",
        dry_run=False,
    )
    sig = LLMSignal(action=Action.SHORT, size_pct=5.0, confidence=0.8, reason="fast cross below")
    from binance_auto_ai.telegram_notify import notify_real_order

    notify_real_order(s, symbol="BTC/USDT:USDT", signal=sig, source="strategy", mark_price_usdt=65432.1)
    assert len(sent) == 1
    assert "65432" in sent[0]
    assert "价格" in sent[0]


def test_format_trade_message_reason_zh() -> None:
    s = Settings(symbol="ZEC/USDT:USDT", telegram_template="default")
    sig = LLMSignal(action=Action.SHORT, size_pct=5.0, confidence=0.8, reason="fast cross below")
    msg = format_trade_message(s, sig, source="strategy")
    assert "快线下穿慢线" in msg
    assert "fast cross below" not in msg


def test_format_trade_message_default() -> None:
    s = Settings(telegram_template="compact")
    sig = LLMSignal(action=Action.LONG, size_pct=50.0, confidence=0.7, reason="test")
    msg = format_trade_message(s, sig, source="strategy", equity_usdt=123.4567)
    assert "BTC/USDT" in msg
    assert "\u505a\u591a" in msg  # zh: 做多


def test_stochastic_cross_state_defined() -> None:
    n = 80
    t = np.arange(n, dtype=np.float64) * 60_000
    c = 100.0 + np.sin(np.linspace(0, 4, n)) * 2.0
    h = c + 0.5
    low = c - 0.5
    v = np.ones(n)
    ohlcv = [[float(t[i]), c[i], h[i], low[i], c[i], v[i]] for i in range(n)]
    h_arr = np.array([b[2] for b in ohlcv])
    l_arr = np.array([b[3] for b in ohlcv])
    c_arr = np.array([b[4] for b in ohlcv])
    st = stochastic_cross_state(h_arr, l_arr, c_arr, 14, 3)
    assert st is not None


def test_atr_positive() -> None:
    n = 40
    h = np.linspace(100, 110, n)
    low = h - 1.0
    c = (h + low) / 2.0
    a = atr_wilder_series(h, low, c, 14)
    assert np.isfinite(a[-1])
    assert float(a[-1]) > 0
