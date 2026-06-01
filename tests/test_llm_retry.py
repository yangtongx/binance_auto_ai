from __future__ import annotations

import httpx
import pytest
from openai import APITimeoutError

from binance_auto_ai.config import Settings
from binance_auto_ai.llm_strategy import llm_decide


def test_llm_decide_retries_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    class _Msg:
        content = '{"action":"hold","size_pct":0,"confidence":0.5,"reason":"t"}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):  # noqa: ANN003, ANN002
            calls["n"] += 1
            if calls["n"] == 1:
                raise APITimeoutError(httpx.Request("POST", "https://example.com/v1"))
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    def _fake_openai(**kwargs):  # noqa: ANN003
        return _Client()

    monkeypatch.setattr("binance_auto_ai.llm_strategy.OpenAI", _fake_openai)

    s = Settings.model_construct(
        openai_api_key="sk-test",
        openai_base_url=None,
        openai_model="gpt-4.1-mini",
        openai_timeout_sec=30.0,
        openai_max_retries=3,
        openai_retry_base_sec=0.01,
        symbol="BTC/USDT:USDT",
    )
    out = llm_decide(s, "ctx")
    assert out.action.value == "hold"
    assert calls["n"] == 2
