"""LLM 信号源：调用 OpenAI 兼容 API，解析 JSON 为 LLMSignal（SIGNAL_SOURCE=llm）。"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError

from binance_auto_ai.config import Settings
from binance_auto_ai.schemas import LLMSignal

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a cautious assistant for Binance USDT-M perpetual futures in ONE-WAY position mode.
You only output a single JSON object, no markdown fences, no extra keys, no commentary.
Schema:
{"action":"long|short|flat|hold","size_pct":number,"confidence":number,"reason":"string"}

Definitions:
- long: want net long exposure (if currently short, model should still say long — the executor will flatten first).
- short: want net short exposure.
- flat: close to flat (reduce-only style intent).
- hold: no trade.
- size_pct: 0-100, meaning how much of the caller's MAX_NOTIONAL_USDT budget to use for opening/adding; for flat use 100 to mean full exit intent.
- confidence: 0-1.

Be conservative: prefer hold when evidence is weak. Reasons must be short."""


def _strip_markdown_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\r?\n?([\s\S]*?)\r?\n?```\s*$", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _first_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    quote: str | None = None
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif quote and ch == quote:
                in_string = False
                quote = None
            continue
        if ch == '"':
            in_string = True
            quote = '"'
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _extract_json_object(text: str) -> dict[str, Any]:
    text = _strip_markdown_fence(text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    blob = _first_balanced_json_object(text)
    if blob:
        return json.loads(blob)
    raise ValueError(f"no parseable JSON object in LLM output: {text[:500]!r}")


def _retryable_status_error(exc: APIStatusError) -> bool:
    code = getattr(exc, "status_code", None)
    return code in (408, 425, 429, 500, 502, 503, 504)


def _parse_llm_response(content: str) -> LLMSignal:
    try:
        raw = _extract_json_object(content)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("LLM output not JSON-parseable: %s | snippet=%r", e, content[:400])
        raise
    if raw.get("action") == "close":
        raw["action"] = "flat"
    try:
        return LLMSignal.model_validate(raw)
    except ValidationError as e:
        logger.warning("LLM JSON failed schema: %s | raw=%r", e, raw)
        raise


def llm_decide(settings: Settings, market_context: str) -> LLMSignal:
    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
        timeout=settings.openai_timeout_sec,
    )
    max_attempts = settings.openai_max_retries
    last_error: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": market_context},
                ],
            )
            content = resp.choices[0].message.content or ""
            return _parse_llm_response(content)
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            last_error = e
            logger.warning(
                "LLM API transient error (%s) attempt %s/%s: %s",
                type(e).__name__,
                attempt,
                max_attempts,
                e,
            )
        except APIStatusError as e:
            if isinstance(e, AuthenticationError):
                logger.error("LLM authentication failed (not retrying): %s", e)
                raise
            if _retryable_status_error(e) and attempt < max_attempts:
                last_error = e
                logger.warning(
                    "LLM API HTTP %s attempt %s/%s: %s",
                    getattr(e, "status_code", "?"),
                    attempt,
                    max_attempts,
                    e,
                )
            else:
                logger.error("LLM API non-retryable or exhausted: %s", e)
                raise
        except OSError as e:
            last_error = e
            logger.warning("LLM network OSError attempt %s/%s: %s", attempt, max_attempts, e)

        if attempt >= max_attempts:
            break
        sleep_s = min(60.0, float(settings.openai_retry_base_sec) * (2 ** (attempt - 1)))
        logger.info("LLM retry sleeping %.1fs before next attempt", sleep_s)
        time.sleep(sleep_s)

    logger.error("LLM API failed after %s attempts", max_attempts)
    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM API failed without specific error")
