"""运行时配置：从 .env / 环境变量 / Docker secrets 加载，字段与 deploy/server.env 对应。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/binance_auto_ai/config.py -> 仓库根目录（"src" 的上一级）
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"
# 官方镜像中可写的会话状态路径（见 Dockerfile / docker-compose）
_DOCKER_STATE_FILE = Path("/app/state/state.json")


def _in_docker() -> bool:
    return Path("/.dockerenv").is_file()


def _docker_writable_state_file() -> Path | None:
    if _in_docker() and _DOCKER_STATE_FILE.parent.is_dir():
        return _DOCKER_STATE_FILE
    return None

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:[A-Za-z0-9._-]+$")

# Docker secrets 约定：若设置了 XXX_FILE，则从该文件读取密钥
_DOCKER_SECRET_MAP = {
    "BINANCE_API_KEY": "BINANCE_API_KEY_FILE",
    "BINANCE_API_SECRET": "BINANCE_API_SECRET_FILE",
    "OPENAI_API_KEY": "OPENAI_API_KEY_FILE",
    "TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN_FILE",
    "TELEGRAM_CHAT_ID": "TELEGRAM_CHAT_ID_FILE",
}


def _load_docker_secrets() -> None:
    """当直接环境变量未设置或为空时，从 ``*_FILE`` 路径加载密钥。

    Docker Compose 的 ``env_file: .env`` 常把 ``BINANCE_API_KEY=`` 留空，
    否则会阻止从 ``/run/secrets/...`` 读取。
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
            # Compose 将 secrets 挂载为 root:root 0600；非 root 须通过 docker-entrypoint.sh 读取
            continue


_load_docker_secrets()


class Settings(BaseSettings):
    """机器人全部可调参数（交易所、策略、选币、仓位、风控、通知、监控面板）。"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- 币安 API ---
    binance_api_key: str = Field(default="", validation_alias="BINANCE_API_KEY")
    binance_api_secret: str = Field(default="", validation_alias="BINANCE_API_SECRET")
    binance_testnet: bool = Field(default=False, validation_alias="BINANCE_TESTNET")
    # 本地 Clash/SSR：http://127.0.0.1:7890 或 socks5://127.0.0.1:1080（socks 需 PySocks）
    binance_https_proxy: str = Field(default="", validation_alias="BINANCE_HTTPS_PROXY")

    # --- LLM（SIGNAL_SOURCE=llm 时必填）---
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")
    openai_timeout_sec: float = Field(default=120.0, gt=0, validation_alias="OPENAI_TIMEOUT_SEC")
    openai_max_retries: int = Field(default=4, ge=1, le=12, validation_alias="OPENAI_MAX_RETRIES")
    openai_retry_base_sec: float = Field(default=1.0, gt=0, le=120, validation_alias="OPENAI_RETRY_BASE_SEC")

    # --- 信号源：llm=大模型；strategy=规则引擎（与回测策略一致）---
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
    # all | directional（多/空/平，跳过观望）| off
    telegram_notify_signals: str = Field(default="directional", validation_alias="TELEGRAM_NOTIFY_SIGNALS")
    telegram_notify_startup: bool = Field(default=True, validation_alias="TELEGRAM_NOTIFY_STARTUP")
    telegram_notify_pool_refresh: bool = Field(default=True, validation_alias="TELEGRAM_NOTIFY_POOL_REFRESH")
    telegram_notify_orders: bool = Field(default=True, validation_alias="TELEGRAM_NOTIFY_ORDERS")
    telegram_notify_errors: bool = Field(default=True, validation_alias="TELEGRAM_NOTIFY_ERRORS")

    use_websocket: bool = Field(default=False, validation_alias="USE_WEBSOCKET")
    ws_reconnect_base_sec: float = Field(default=1.0, gt=0.0, le=120.0, validation_alias="WS_RECONNECT_BASE_SEC")
    ws_reconnect_max_sec: float = Field(default=60.0, gt=0.0, le=3600.0, validation_alias="WS_RECONNECT_MAX_SEC")
    ws_reconnect_jitter: float = Field(default=0.25, ge=0.0, le=1.0, validation_alias="WS_RECONNECT_JITTER")

    # --- 交易对与选币 ---
    symbol: str = Field(default="BTC/USDT:USDT", validation_alias="SYMBOL")
    # single=只交易 SYMBOL；signal_pick=候选池每分钟选最强信号，同时只持一仓
    symbol_mode: str = Field(default="single", validation_alias="SYMBOL_MODE")
    symbol_candidates: str = Field(
        default="auto",
        validation_alias="SYMBOL_CANDIDATES",
    )
    symbol_candidates_count: int = Field(default=5, ge=2, le=12, validation_alias="SYMBOL_CANDIDATES_COUNT")
    # 逗号分隔的综合排序：abs_change,open_interest,liquidity（liquidity=24h 成交额）
    symbol_candidates_rank_by: str = Field(
        default="abs_change,open_interest,liquidity",
        validation_alias="SYMBOL_CANDIDATES_RANK_BY",
    )
    # 与 RANK_BY 顺序对应的权重；空=均分
    symbol_candidates_rank_weights: str = Field(
        default="0.4,0.3,0.3",
        validation_alias="SYMBOL_CANDIDATES_RANK_WEIGHTS",
    )
    # 仅流动性下限（不参与排序）；0=未按成交量排序时可关闭
    symbol_candidates_min_quote_volume_usdt: float = Field(
        default=1_000_000.0,
        ge=0.0,
        validation_alias="SYMBOL_CANDIDATES_MIN_QUOTE_VOLUME_USDT",
    )
    symbol_candidates_exclude: str = Field(
        default="",
        validation_alias="SYMBOL_CANDIDATES_EXCLUDE",
    )
    symbol_candidates_refresh_hours: float = Field(
        default=2.0,
        gt=0.0,
        le=168.0,
        validation_alias="SYMBOL_CANDIDATES_REFRESH_HOURS",
    )
    # >0 时覆盖 ``SYMBOL_CANDIDATES_REFRESH_HOURS``，用于亚小时刷新
    symbol_candidates_refresh_minutes: float = Field(
        default=0.0,
        ge=0.0,
        le=24.0 * 60.0,
        validation_alias="SYMBOL_CANDIDATES_REFRESH_MINUTES",
    )
    symbol_candidates_filter_min_notional: bool = Field(
        default=True,
        validation_alias="SYMBOL_CANDIDATES_FILTER_MIN_NOTIONAL",
    )
    # 剔除 |24h 涨跌幅| 超过此值的币（0=关闭），避免自动池追暴涨暴跌
    symbol_candidates_max_abs_change_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=1000.0,
        validation_alias="SYMBOL_CANDIDATES_MAX_ABS_CHANGE_PCT",
    )
    # signal_pick 换币迟滞：仅当新标的方向置信度 ≥ 在手仓置信度 + 此值才换币（0=每分钟都可换，抖动大）
    symbol_rotation_hysteresis: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        validation_alias="SYMBOL_ROTATION_HYSTERESIS",
    )
    timeframe: str = Field(default="1m", validation_alias="TIMEFRAME")
    klines_limit: int = Field(default=120, ge=10, le=1500, validation_alias="KLINES_LIMIT")
    # --- 仓位与名义金额 ---
    max_notional_usdt: float = Field(default=50.0, gt=0, validation_alias="MAX_NOTIONAL_USDT")
    # fixed：MAX_NOTIONAL_USDT × size_pct
    # equity_leverage：钱包总权益 × LEVERAGE × size_pct
    # available_margin_leverage：可用保证金 × LEVERAGE × size_pct（实盘常用）
    position_sizing: str = Field(default="fixed", validation_alias="POSITION_SIZING")
    leverage: float = Field(default=1.0, ge=1.0, le=150.0, validation_alias="LEVERAGE")
    # fixed=用 LEVERAGE；max=用「该下单币交易所允许的最大杠杆」（LEVERAGE 作为取不到时的回退）
    leverage_mode: str = Field(default="fixed", validation_alias="LEVERAGE_MODE")
    dry_run: bool = Field(default=True, validation_alias="DRY_RUN")  # true=只打日志不下单

    min_confidence: float = Field(default=0.55, ge=0.0, le=1.0, validation_alias="MIN_CONFIDENCE")

    # --- 主动离场（按入场价的价格变动百分比；0=关闭。注意：杠杆 L 下对权益的影响≈pct×L）---
    # 止损：相对入场价的不利变动达到此 %（如 2=逆向 2%）即平仓
    exit_stop_loss_pct: float = Field(default=0.0, ge=0.0, le=100.0, validation_alias="EXIT_STOP_LOSS_PCT")
    # 止盈：相对入场价的有利变动达到此 % 即平仓
    exit_take_profit_pct: float = Field(default=0.0, ge=0.0, le=1000.0, validation_alias="EXIT_TAKE_PROFIT_PCT")
    # 移动止盈：盈利曾达到该 %（armed）后，从最高浮盈回撤达到该 % 即平仓
    exit_trailing_pct: float = Field(default=0.0, ge=0.0, le=100.0, validation_alias="EXIT_TRAILING_PCT")
    # 持仓超时：持仓时间达到该分钟数即平仓（0=关闭）；进程重启后以再次见到该仓的时刻重新计时
    exit_max_hold_minutes: float = Field(default=0.0, ge=0.0, le=100_000.0, validation_alias="EXIT_MAX_HOLD_MINUTES")
    # 按「回报率 ROE = 收益/保证金 = 价格变动% × 杠杆」离场（0=关闭）。
    # 止盈：ROE 达到该 % 即平仓（100 = 浮盈达到该仓保证金的 100%）
    exit_take_profit_roe_pct: float = Field(default=0.0, ge=0.0, le=100_000.0, validation_alias="EXIT_TAKE_PROFIT_ROE_PCT")
    # 止损：ROE 跌到 -该 % 即平仓（如 80 = 亏掉 80% 保证金）
    exit_stop_loss_roe_pct: float = Field(default=0.0, ge=0.0, le=100_000.0, validation_alias="EXIT_STOP_LOSS_ROE_PCT")

    exchange_timeout_ms: int = Field(default=30_000, ge=1_000, validation_alias="EXCHANGE_TIMEOUT_MS")
    position_poll_interval_sec: float = Field(default=0.15, gt=0, validation_alias="POSITION_POLL_INTERVAL_SEC")
    position_poll_timeout_sec: float = Field(default=5.0, gt=0, validation_alias="POSITION_POLL_TIMEOUT_SEC")

    # auto=读币安持仓模式；oneway|hedge=强制单向/双向（须与账户一致，否则 -4061）
    position_mode: str = Field(default="auto", validation_alias="POSITION_MODE")

    # --- 会话风控（UTC 日）---
    max_trades_per_day: int = Field(default=0, ge=0, validation_alias="MAX_TRADES_PER_DAY")
    max_daily_loss_usdt: float = Field(default=0.0, ge=0, validation_alias="MAX_DAILY_LOSS_USDT")
    daily_loss_warn_ratio: float = Field(default=0.8, ge=0.0, le=1.0, validation_alias="DAILY_LOSS_WARN_RATIO")
    state_file: Path = Field(default=_REPO_ROOT / ".binance_auto_ai_state.json", validation_alias="STATE_FILE")

    observability_host: str = Field(default="127.0.0.1", validation_alias="OBSERVABILITY_HOST")
    observability_port: int = Field(default=0, ge=0, le=65535, validation_alias="OBSERVABILITY_PORT")

    @field_validator("binance_https_proxy", mode="before")
    @classmethod
    def _strip_proxy(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

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

    @field_validator(
        "signal_source",
        "strategy_name",
        "position_sizing",
        "symbol_mode",
        "symbol_candidates_rank_by",
        mode="before",
    )
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

    @field_validator("telegram_notify_signals", mode="before")
    @classmethod
    def _telegram_notify_signals_in(cls, v: object) -> str:
        return str(v).strip().lower()

    @field_validator("telegram_notify_signals")
    @classmethod
    def _telegram_notify_signals_valid(cls, v: str) -> str:
        if v not in ("all", "directional", "off"):
            raise ValueError("TELEGRAM_NOTIFY_SIGNALS must be all, directional, or off")
        return v

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
    def _validate_symbol_mode_config(self) -> Settings:
        if self.symbol_mode != "signal_pick":
            return self
        if self.signal_source != "strategy":
            raise ValueError("SYMBOL_MODE=signal_pick requires SIGNAL_SOURCE=strategy (not llm)")
        if self.use_websocket:
            raise ValueError("SYMBOL_MODE=signal_pick does not support USE_WEBSOCKET=true")
        from binance_auto_ai.symbol_picker import parse_symbol_candidates

        if self.symbol_candidates_is_auto():
            for sym in parse_symbol_candidates(self.symbol_candidates_exclude):
                if sym and not _SYMBOL_RE.match(sym):
                    raise ValueError(f"SYMBOL_CANDIDATES_EXCLUDE entry {sym!r} is invalid")
            metrics = self.candidate_rank_metrics()
            weights_raw = self.symbol_candidates_rank_weights.strip()
            if weights_raw:
                parts = [p for p in weights_raw.split(",") if p.strip()]
                if len(parts) != len(metrics):
                    raise ValueError(
                        "SYMBOL_CANDIDATES_RANK_WEIGHTS must have one number per RANK_BY metric "
                        f"(got {len(parts)} weights for {len(metrics)} metrics)"
                    )
                for p in parts:
                    try:
                        if float(p.strip()) < 0:
                            raise ValueError
                    except ValueError as e:
                        raise ValueError(
                            "SYMBOL_CANDIDATES_RANK_WEIGHTS must be non-negative numbers"
                        ) from e
            return self
        cands = self.manual_candidate_symbols()
        if len(cands) < 2:
            raise ValueError(
                "SYMBOL_MODE=signal_pick requires SYMBOL_CANDIDATES=auto or at least 2 manual symbols"
            )
        if len(cands) > 12:
            raise ValueError("SYMBOL_CANDIDATES supports at most 12 manual symbols")
        for sym in cands:
            if not _SYMBOL_RE.match(sym):
                raise ValueError(
                    f"SYMBOL_CANDIDATES entry {sym!r} must match BASE/QUOTE:SETTLE (e.g. DOGE/USDT:USDT)"
                )
        for sym in parse_symbol_candidates(self.symbol_candidates_exclude):
            if sym and not _SYMBOL_RE.match(sym):
                raise ValueError(f"SYMBOL_CANDIDATES_EXCLUDE entry {sym!r} is invalid")
        return self

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
            from binance_auto_ai.strategy_factory import COMPOSITE_CHILD_STRATEGIES, parse_composite_members

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

    @field_validator("position_sizing")
    @classmethod
    def _validate_position_sizing(cls, v: str) -> str:
        if v not in ("fixed", "equity_leverage", "available_margin_leverage"):
            raise ValueError(
                "POSITION_SIZING must be fixed|equity_leverage|available_margin_leverage"
            )
        return v

    @field_validator("leverage_mode", mode="before")
    @classmethod
    def _normalize_leverage_mode(cls, v: object) -> str:
        return str(v).strip().lower()

    @field_validator("leverage_mode")
    @classmethod
    def _validate_leverage_mode(cls, v: str) -> str:
        if v not in ("fixed", "max"):
            raise ValueError("LEVERAGE_MODE must be fixed|max")
        return v

    @field_validator("symbol_mode")
    @classmethod
    def _validate_symbol_mode(cls, v: str) -> str:
        if v not in ("single", "signal_pick"):
            raise ValueError("SYMBOL_MODE must be single|signal_pick")
        return v

    @field_validator("symbol_candidates_rank_by")
    @classmethod
    def _validate_symbol_candidates_rank_by(cls, v: str) -> str:
        from binance_auto_ai.symbol_universe import parse_rank_metrics

        metrics = parse_rank_metrics(str(v))
        if not metrics:
            raise ValueError(
                "SYMBOL_CANDIDATES_RANK_BY needs at least one of: "
                "abs_change, change, open_interest, liquidity, quote_volume, "
                "momentum (trend), funding, abs_funding, random"
            )
        return ",".join(metrics)

    @field_validator("symbol_candidates_rank_weights", mode="before")
    @classmethod
    def _strip_rank_weights(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("symbol_candidates", mode="before")
    @classmethod
    def _strip_symbol_candidates(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    def symbol_candidates_is_auto(self) -> bool:
        from binance_auto_ai.symbol_universe import is_auto_symbol_candidates

        return self.symbol_mode == "signal_pick" and is_auto_symbol_candidates(self.symbol_candidates)

    def manual_candidate_symbols(self) -> list[str]:
        from binance_auto_ai.symbol_picker import parse_symbol_candidates
        from binance_auto_ai.symbol_universe import is_auto_symbol_candidates

        if self.symbol_mode == "single":
            return [self.symbol]
        raw = [
            p
            for p in parse_symbol_candidates(self.symbol_candidates)
            if p and not is_auto_symbol_candidates(p)
        ]
        if not raw:
            return [self.symbol]
        return raw

    def candidate_symbols(self) -> list[str]:
        """Manual list only; auto pool is resolved at runtime via ``CandidatePool``."""
        return self.manual_candidate_symbols()

    def candidate_rank_metrics(self) -> list[str]:
        from binance_auto_ai.symbol_universe import parse_rank_metrics

        return parse_rank_metrics(self.symbol_candidates_rank_by)

    def candidate_rank_weights(self) -> list[float]:
        from binance_auto_ai.symbol_universe import parse_rank_weights

        return parse_rank_weights(self.candidate_rank_metrics(), self.symbol_candidates_rank_weights)

    def active_exit_enabled(self) -> bool:
        """是否启用任一主动离场规则（止损/止盈/移动止盈/超时）。"""
        return (
            self.exit_stop_loss_pct > 0.0
            or self.exit_take_profit_pct > 0.0
            or self.exit_trailing_pct > 0.0
            or self.exit_max_hold_minutes > 0.0
            or self.exit_take_profit_roe_pct > 0.0
            or self.exit_stop_loss_roe_pct > 0.0
        )

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
        # .env 常为仓库相对路径；容器内 /app 不可写
        if p.name == ".binance_auto_ai_state.json":
            docker_path = _docker_writable_state_file()
            if docker_path is not None:
                return docker_path
        return _REPO_ROOT / p
