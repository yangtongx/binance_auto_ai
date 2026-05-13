from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/futures_llm_bot/config.py -> repository root (parent of "src")
_REPO_ROOT = Path(__file__).resolve().parents[2]

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:[A-Za-z0-9._-]+$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    binance_api_key: str = Field(default="", validation_alias="BINANCE_API_KEY")
    binance_api_secret: str = Field(default="", validation_alias="BINANCE_API_SECRET")
    binance_testnet: bool = Field(default=True, validation_alias="BINANCE_TESTNET")

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")
    openai_timeout_sec: float = Field(default=120.0, gt=0, validation_alias="OPENAI_TIMEOUT_SEC")
    openai_max_retries: int = Field(default=4, ge=1, le=12, validation_alias="OPENAI_MAX_RETRIES")
    openai_retry_base_sec: float = Field(default=1.0, gt=0, le=120, validation_alias="OPENAI_RETRY_BASE_SEC")

    # llm: OpenAI-compatible chat API. strategy: rule engine (same as futures-llm-backtest sma_cross).
    signal_source: str = Field(default="strategy", validation_alias="SIGNAL_SOURCE")
    strategy_name: str = Field(default="sma_cross", validation_alias="STRATEGY_NAME")
    strategy_fast: int = Field(default=10, ge=2, le=500, validation_alias="STRATEGY_FAST")
    strategy_slow: int = Field(default=30, ge=3, le=1500, validation_alias="STRATEGY_SLOW")
    strategy_size_pct: float = Field(default=100.0, ge=0.0, le=100.0, validation_alias="STRATEGY_SIZE_PCT")
    strategy_confidence: float = Field(default=0.8, ge=0.0, le=1.0, validation_alias="STRATEGY_CONFIDENCE")
    strategy_rsi_period: int = Field(default=14, ge=2, le=500, validation_alias="STRATEGY_RSI_PERIOD")
    strategy_rsi_oversold: float = Field(default=30.0, gt=0.0, lt=100.0, validation_alias="STRATEGY_RSI_OVERSOLD")
    strategy_rsi_overbought: float = Field(default=70.0, gt=0.0, lt=100.0, validation_alias="STRATEGY_RSI_OVERBOUGHT")
    strategy_macd_signal: int = Field(default=9, ge=1, le=200, validation_alias="STRATEGY_MACD_SIGNAL")
    strategy_bb_period: int = Field(default=20, ge=3, le=1500, validation_alias="STRATEGY_BB_PERIOD")
    strategy_bb_std: float = Field(default=2.0, gt=0.0, le=10.0, validation_alias="STRATEGY_BB_STD")

    symbol: str = Field(default="BTC/USDT:USDT", validation_alias="SYMBOL")
    timeframe: str = Field(default="1m", validation_alias="TIMEFRAME")
    klines_limit: int = Field(default=120, ge=10, le=1500, validation_alias="KLINES_LIMIT")
    max_notional_usdt: float = Field(default=50.0, gt=0, validation_alias="MAX_NOTIONAL_USDT")
    dry_run: bool = Field(default=True, validation_alias="DRY_RUN")

    min_confidence: float = Field(default=0.55, ge=0.0, le=1.0, validation_alias="MIN_CONFIDENCE")

    exchange_timeout_ms: int = Field(default=30_000, ge=1_000, validation_alias="EXCHANGE_TIMEOUT_MS")
    position_poll_interval_sec: float = Field(default=0.15, gt=0, validation_alias="POSITION_POLL_INTERVAL_SEC")
    position_poll_timeout_sec: float = Field(default=5.0, gt=0, validation_alias="POSITION_POLL_TIMEOUT_SEC")

    # auto: call Binance position mode API when keys exist; oneway|hedge: trust env
    position_mode: str = Field(default="auto", validation_alias="POSITION_MODE")

    max_trades_per_day: int = Field(default=0, ge=0, validation_alias="MAX_TRADES_PER_DAY")
    max_daily_loss_usdt: float = Field(default=0.0, ge=0, validation_alias="MAX_DAILY_LOSS_USDT")
    daily_loss_warn_ratio: float = Field(default=0.8, ge=0.0, le=1.0, validation_alias="DAILY_LOSS_WARN_RATIO")
    state_file: Path = Field(default=_REPO_ROOT / ".futures_llm_bot_state.json", validation_alias="STATE_FILE")

    observability_host: str = Field(default="127.0.0.1", validation_alias="OBSERVABILITY_HOST")
    observability_port: int = Field(default=0, ge=0, le=65535, validation_alias="OBSERVABILITY_PORT")

    @field_validator("binance_api_key", "binance_api_secret", "openai_api_key", mode="before")
    @classmethod
    def _strip_secrets(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("openai_base_url", mode="before")
    @classmethod
    def _validate_base_url(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        parsed = urlparse(s)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("OPENAI_BASE_URL must be an absolute http(s) URL with a host")
        return s

    @field_validator("signal_source", "strategy_name", mode="before")
    @classmethod
    def _normalize_lowercase_choice(cls, v: object) -> str:
        return str(v).strip().lower()

    @model_validator(mode="after")
    def _validate_strategy_params(self) -> Settings:
        if self.signal_source not in ("llm", "strategy"):
            raise ValueError("SIGNAL_SOURCE must be llm or strategy")
        if self.signal_source != "strategy":
            return self
        name = self.strategy_name
        if name == "sma_cross":
            if self.strategy_fast >= self.strategy_slow:
                raise ValueError("STRATEGY_FAST must be < STRATEGY_SLOW for sma_cross")
        elif name == "rsi":
            if self.strategy_rsi_oversold >= self.strategy_rsi_overbought:
                raise ValueError("STRATEGY_RSI_OVERSOLD must be < STRATEGY_RSI_OVERBOUGHT")
        elif name == "macd":
            if self.strategy_fast >= self.strategy_slow:
                raise ValueError("STRATEGY_FAST/STRATEGY_SLOW are MACD fast/slow spans; FAST must be < SLOW")
        elif name in ("bollinger", "bb"):
            pass
        else:
            allowed = "sma_cross|rsi|macd|bollinger|bb"
            raise ValueError(f"Unknown STRATEGY_NAME={self.strategy_name!r} (supported: {allowed})")
        return self

    @field_validator("symbol", mode="before")
    @classmethod
    def _validate_symbol(cls, v: object) -> str:
        s = str(v).strip()
        if not _SYMBOL_RE.match(s):
            raise ValueError(
                "SYMBOL must match CCXT linear perpetual form BASE/QUOTE:SETTLE (e.g. BTC/USDT:USDT)"
            )
        return s

    @field_validator("state_file", mode="before")
    @classmethod
    def _resolve_state_file(cls, v: object) -> Path:
        p = Path(v)  # type: ignore[arg-type]
        if p.is_absolute():
            return p
        return _REPO_ROOT / p
