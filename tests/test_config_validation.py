from __future__ import annotations

import pytest


def test_symbol_must_match_ccxt_linear_form(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYMBOL", "BTCUSDT")
    from futures_llm_bot.config import Settings

    with pytest.raises(ValueError, match="SYMBOL"):
        Settings()


def test_openai_base_url_must_be_http_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYMBOL", "BTC/USDT:USDT")
    monkeypatch.setenv("OPENAI_BASE_URL", "ftp://example.com/v1")
    from futures_llm_bot.config import Settings

    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        Settings()
