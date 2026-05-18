from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/futures_llm_bot/config.py -> repository root (parent of "src")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"
# Writable session state in the official image (see Dockerfile / docker-compose).
_DOCKER_STATE_FILE = Path("/app/state/state.json")


def _in_docker() -> bool:
    return Path("/.dockerenv").is_file()


def _docker_writable_state_file() -> Path | None:
    if _in_docker() and _DOCKER_STATE_FILE.parent.is_dir():
        return _DOCKER_STATE_FILE
    return None

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:[A-Za-z0-9._-]+$")

# Docker secrets convention: if XXX_FILE is set, read the secret from that file.
_DOCKER_SECRET_MAP = {
    "BINANCE_API_KEY": "BINANCE_API_KEY_FILE",
    "BINANCE_API_SECRET": "BINANCE_API_SECRET_FILE",
    "OPENAI_API_KEY": "OPENAI_API_KEY_FILE",
}


def _load_docker_secrets() -> None:
    """Load secrets from ``*_FILE`` paths when the direct env var is unset or empty.

    ``env_file: .env`` in Docker Compose often sets ``BINANCE_API_KEY=`` (empty), which
    would otherwise block reading ``/run/secrets/...``.
    """
    for env_key, file_key in _DOCKER_SECRET_MAP.items():
        if os.environ.get(env_key, "").strip():
            continue
        if file_key not in os.environ:
            continue
        path = Path(os.environ[file_key])
        if not path.is_file():
            continue
        try:
            os.environ[env_key] = path.read_text(encoding="utf-8").strip()
        except PermissionError:
            # Compose mounts secrets as root:root 0600; non-root must use docker-entrypoint.sh.
            continue


_load_docker_secrets()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else None,
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

    strategy_ichimoku_tenkan: int = Field(default=9, ge=2, le=200, validation_alias="STRATEGY_ICHIMOKU_TENKAN")
    strategy_ichimoku_kijun: int = Field(default=26, ge=3, le=500, validation_alias="STRATEGY_ICHIMOKU_KIJUN")
    strategy_ichimoku_senkou_b: int = Field(default=52, ge=4, le=1500, validation_alias="STRATEGY_ICHIMOKU_SENKOU_B")

    strategy_fib_lookback: int = Field(default=50, ge=10, le=5000, validation_alias="STRATEGY_FIB_LOOKBACK")
    strategy_fib_level: str = Field(default="0.618", validation_alias="STRATEGY_FIB_LEVEL")

    strategy_vp_bars: int = Field(default=48, ge=10, le=5000, validation_alias="STRATEGY_VP_BARS")
    strategy_vp_bins: int = Field(default=24, ge=4, le=500, validation_alias="STRATEGY_VP_BINS")

    strategy_stoch_k: int = Field(default=14, ge=2, le=200, validation_alias="STRATEGY_STOCH_K")
    strategy_stoch_d: int = Field(default=3, ge=1, le=100, validation_alias="STRATEGY_STOCH_D")
    strategy_stoch_oversold: float = Field(default=20.0, gt=0.0, lt=100.0, validation_alias="STRATEGY_STOCH_OVERSOLD")
    strategy_stoch_overbought: float = Field(
        default=80.0, gt=0.0, lt=100.0, validation_alias="STRATEGY_STOCH_OVERBOUGHT"
    )

    strategy_atr_period: int = Field(default=14, ge=2, le=500, validation_alias="STRATEGY_ATR_PERIOD")
    strategy_atr_mult: float = Field(default=1.5, gt=0.0, le=20.0, validation_alias="STRATEGY_ATR_MULT")

    ml_backend: str = Field(default="", validation_alias="ML_BACKEND")
    ml_model_path: str = Field(default="", validation_alias="ML_MODEL_PATH")
    strategy_ml_window: int = Field(default=32, ge=8, le=500, validation_alias="STRATEGY_ML_WINDOW")
    ml_torch_arch: str = Field(default="mlp", validation_alias="ML_TORCH_ARCH")
    ml_hot_reload: bool = Field(default=True, validation_alias="ML_HOT_RELOAD")
    ml_hot_reload_interval_sec: float = Field(
        default=30.0,
        ge=1.0,
        le=3600.0,
        validation_alias="ML_HOT_RELOAD_INTERVAL_SEC",
    )

    composite_members: str = Field(default="", validation_alias="COMPOSITE_MEMBERS")
    composite_mode: str = Field(default="majority", validation_alias="COMPOSITE_MODE")
    composite_weights: str = Field(default="", validation_alias="COMPOSITE_WEIGHTS")

    strategy_vol_window: int = Field(default=20, ge=3, le=500, validation_alias="STRATEGY_VOL_WINDOW")
    strategy_vol_ref_window: int = Field(default=100, ge=5, le=5000, validation_alias="STRATEGY_VOL_REF_WINDOW")
    strategy_vol_sensitivity: float = Field(
        default=10.0, gt=0.0, le=50.0, validation_alias="STRATEGY_VOL_SENSITIVITY"
    )

    rl_model_path: str = Field(default="", validation_alias="RL_MODEL_PATH")
    rl_window: int = Field(default=32, ge=8, le=500, validation_alias="RL_WINDOW")

    risk_var_window: int = Field(default=0, ge=0, le=5000, validation_alias="RISK_VAR_WINDOW")
    risk_var_alpha: float = Field(default=0.05, gt=0.0, lt=0.5, validation_alias="RISK_VAR_ALPHA")
    risk_var_block: bool = Field(default=False, validation_alias="RISK_VAR_BLOCK")
    risk_var_tail_limit: float = Field(default=-0.02, validation_alias="RISK_VAR_TAIL_LIMIT")
    risk_corr_aux_symbol: str = Field(default="", validation_alias="RISK_CORR_AUX_SYMBOL")
    risk_corr_log_every: int = Field(default=20, ge=1, le=10_000, validation_alias="RISK_CORR_LOG_EVERY")

    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", validation_alias="TELEGRAM_CHAT_ID")
    telegram_template: str = Field(default="default", validation_alias="TELEGRAM_TEMPLATE")
    telegram_message_template: str = Field(default="", validation_alias="TELEGRAM_MESSAGE_TEMPLATE")
    telegram_parse_mode: str = Field(default="", validation_alias="TELEGRAM_PARSE_MODE")

    use_websocket: bool = Field(default=False, validation_alias="USE_WEBSOCKET")
    ws_reconnect_base_sec: float = Field(default=1.0, gt=0.0, le=120.0, validation_alias="WS_RECONNECT_BASE_SEC")
    ws_reconnect_max_sec: float = Field(default=60.0, gt=0.0, le=3600.0, validation_alias="WS_RECONNECT_MAX_SEC")
    ws_reconnect_jitter: float = Field(default=0.25, ge=0.0, le=1.0, validation_alias="WS_RECONNECT_JITTER")

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

    @field_validator("ml_backend", "strategy_fib_level", "ml_torch_arch", mode="before")
    @classmethod
    def _strip_optional_choice(cls, v: object) -> str:
        return str(v).strip()

    @field_validator("telegram_template", "telegram_message_template", mode="before")
    @classmethod
    def _telegram_template_raw(cls, v: object) -> str:
        return str(v).strip()

    @field_validator("telegram_parse_mode", mode="before")
    @classmethod
    def _telegram_parse_mode_in(cls, v: object) -> str:
        return str(v).strip()

    @field_validator("composite_mode", mode="before")
    @classmethod
    def _composite_mode_norm(cls, v: object) -> str:
        return str(v).strip().lower()

    @field_validator("risk_corr_aux_symbol", mode="before")
    @classmethod
    def _risk_corr_symbol(cls, v: object) -> str:
        s = str(v).strip()
        if not s:
            return ""
        if not _SYMBOL_RE.match(s):
            raise ValueError(
                "RISK_CORR_AUX_SYMBOL must match CCXT linear perpetual form (e.g. ETH/USDT:USDT) or be empty"
            )
        return s

    @model_validator(mode="after")
    def _normalize_telegram_parse_mode(self) -> Settings:
        pm = self.telegram_parse_mode
        if not pm:
            return self
        u = pm.upper()
        if u == "HTML":
            object.__setattr__(self, "telegram_parse_mode", "HTML")
        elif u == "MARKDOWN":
            object.__setattr__(self, "telegram_parse_mode", "Markdown")
        elif u == "MARKDOWNV2":
            object.__setattr__(self, "telegram_parse_mode", "MarkdownV2")
        else:
            raise ValueError("TELEGRAM_PARSE_MODE must be HTML, Markdown, or MarkdownV2")
        return self

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
        elif name in ("ichimoku", "ichi"):
            if not (self.strategy_ichimoku_tenkan < self.strategy_ichimoku_kijun < self.strategy_ichimoku_senkou_b):
                raise ValueError(
                    "STRATEGY_ICHIMOKU_TENKAN < KIJUN < SENKOU_B required for ichimoku",
                )
        elif name in ("fibonacci", "fib"):
            lf = self.strategy_fib_level
            if lf not in ("0.382", "0.5", "0.618"):
                raise ValueError("STRATEGY_FIB_LEVEL must be 0.382, 0.5, or 0.618")
        elif name in ("volume_profile", "vp"):
            pass
        elif name in ("stochastic", "stoch"):
            if self.strategy_stoch_oversold >= self.strategy_stoch_overbought:
                raise ValueError("STRATEGY_STOCH_OVERSOLD must be < STRATEGY_STOCH_OVERBOUGHT")
        elif name in ("atr_breakout", "atr"):
            pass
        elif name == "ml":
            if not self.ml_model_path.strip():
                raise ValueError("ML_MODEL_PATH is required when STRATEGY_NAME=ml")
            b = self.ml_backend.lower().strip()
            if b not in ("torch", "pytorch", "tensorflow", "tf", "keras"):
                raise ValueError(
                    "ML_BACKEND must be torch|pytorch|tensorflow|tf|keras when STRATEGY_NAME=ml",
                )
            arch = self.ml_torch_arch.lower().strip()
            if b in ("torch", "pytorch"):
                if arch not in ("mlp", "lstm", "transformer"):
                    raise ValueError("ML_TORCH_ARCH must be mlp|lstm|transformer for PyTorch backend")
            elif arch not in ("mlp",):
                raise ValueError("ML_TORCH_ARCH must be mlp when using TensorFlow backend (sequence models: use torch)")
        elif name == "rsi_adaptive":
            if self.strategy_rsi_oversold >= self.strategy_rsi_overbought:
                raise ValueError("STRATEGY_RSI_OVERSOLD must be < STRATEGY_RSI_OVERBOUGHT")
        elif name == "rl_sb3":
            if not self.rl_model_path.strip():
                raise ValueError("RL_MODEL_PATH is required when STRATEGY_NAME=rl_sb3")
        elif name == "composite":
            from futures_llm_bot.strategy_factory import COMPOSITE_CHILD_STRATEGIES, parse_composite_members

            if self.composite_mode not in ("majority", "weighted", "unanimous", "first"):
                raise ValueError("COMPOSITE_MODE must be majority|weighted|unanimous|first")
            mems = parse_composite_members(self.composite_members)
            if not mems:
                raise ValueError("COMPOSITE_MEMBERS is required when STRATEGY_NAME=composite (comma-separated ids)")
            if any(m == "composite" for m in mems):
                raise ValueError("nested composite strategies are not supported")
            for m in mems:
                if m not in COMPOSITE_CHILD_STRATEGIES:
                    raise ValueError(
                        f"unknown composite member {m!r} (supported leaf strategies only, not 'composite')"
                    )
            if "ml" in mems and not self.ml_model_path.strip():
                raise ValueError("ML_MODEL_PATH is required when COMPOSITE_MEMBERS includes ml")
            if "rl_sb3" in mems and not self.rl_model_path.strip():
                raise ValueError("RL_MODEL_PATH is required when COMPOSITE_MEMBERS includes rl_sb3")
            if self.composite_mode == "weighted" and self.composite_weights.strip():
                parts = [x.strip() for x in self.composite_weights.split(",") if x.strip()]
                if len(parts) != len(mems):
                    raise ValueError("COMPOSITE_WEIGHTS must have one float per composite member")
        else:
            allowed = (
                "sma_cross|rsi|rsi_adaptive|macd|bollinger|bb|ichimoku|ichi|fibonacci|fib|volume_profile|vp|"
                "stochastic|stoch|atr_breakout|atr|ml|composite|rl_sb3"
            )
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
        # .env often keeps a repo-relative path; /app is not writable in the container image.
        if p.name == ".futures_llm_bot_state.json":
            docker_path = _docker_writable_state_file()
            if docker_path is not None:
                return docker_path
        return _REPO_ROOT / p
