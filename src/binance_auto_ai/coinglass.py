"""CoinGlass V4 衍生品数据（可选）：聚合持仓量变化、聚合资金费率，用于选币。

- base: https://open-api-v4.coinglass.com ，鉴权头 ``CG-API-KEY``。
- 只用一个快照端点 ``/api/futures/coins-markets``（一次拿全市场每币聚合数据），按 TTL 缓存。
- 全程「可选 + 失败降级」：未装 requests / key 为空 / 请求失败 / 字段缺失 → 返回空，
  调用方（symbol_universe）会让相关维度自动掉出，不影响主流程。

字段名按 CoinGlass 实际返回容错解析（V4 字段可能随版本调整）；解析不到会记一次 debug 日志，
便于按你 key 的真实响应校准。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from binance_auto_ai.config import Settings
from binance_auto_ai.exchange_env import normalize_proxy_url, resolve_binance_proxy

logger = logging.getLogger(__name__)

_COINS_MARKETS_PATH = "/api/futures/coins-markets"

# 容错字段名（按优先级）
_SYMBOL_KEYS = ("symbol", "coin", "baseAsset", "base")
_OI_CHANGE_KEYS = (
    "openInterestChangePercent24h",
    "oiChangePercent24h",
    "openInterestChangePercent",
    "h24OpenInterestChangePercent",
    "oi_change_percent_24h",
    "openInterestChange24hPercent",
    "openInterestChangePercent4h",
)
_FUNDING_KEYS = (
    "fundingRate",
    "avgFundingRate",
    "fundingRatePercent",
    "fundingRateValue",
    "avgFundingRatePercent",
)


def _as_float(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _pick(row: dict[str, Any], exact_keys: tuple[str, ...], *, substrs: tuple[str, ...] | None = None) -> float | None:
    for k in exact_keys:
        if k in row:
            f = _as_float(row[k])
            if f is not None:
                return f
    if substrs:
        for k, val in row.items():
            kl = str(k).lower()
            if all(s in kl for s in substrs):
                f = _as_float(val)
                if f is not None:
                    return f
    return None


def _row_symbol(row: dict[str, Any]) -> str | None:
    for k in _SYMBOL_KEYS:
        raw = row.get(k)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().upper()
    return None


def normalize_coin_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    """把 coins-markets 行列表归一为 ``{COIN: {oi_change_pct, funding_rate}}``（纯函数，便于测试）。"""
    out: dict[str, dict[str, float | None]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = _row_symbol(row)
        if not sym:
            continue
        oi_change = _pick(
            row, _OI_CHANGE_KEYS, substrs=("open", "change", "percent")
        )
        if oi_change is None:
            oi_change = _pick(row, (), substrs=("oi", "change", "percent"))
        funding = _pick(row, _FUNDING_KEYS, substrs=("funding", "rate"))
        out[sym] = {"oi_change_pct": oi_change, "funding_rate": funding}
    return out


class CoinglassClient:
    """轻量 CoinGlass V4 客户端（requests，懒加载；复用 BINANCE_HTTPS_PROXY 代理）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.coinglass_api_key
        self._base = settings.coinglass_base_url.rstrip("/")
        self._timeout = float(settings.coinglass_timeout_sec)
        self._ttl = float(settings.coinglass_cache_ttl_sec)
        self._cache_ts = 0.0
        self._cache: dict[str, dict[str, float | None]] = {}
        proxy = resolve_binance_proxy(settings)
        self._proxies = None
        if proxy:
            u = normalize_proxy_url(proxy)
            self._proxies = {"http": u, "https": u}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            import requests  # 懒加载：未装 .[coinglass] 时优雅降级
        except ImportError:
            logger.warning("CoinGlass disabled: 'requests' not installed (pip install -e \".[coinglass]\")")
            return None
        headers = {"CG-API-KEY": self._api_key, "Accept": "application/json"}
        try:
            resp = requests.get(
                self._base + path,
                params=params or {},
                headers=headers,
                timeout=self._timeout,
                proxies=self._proxies,
            )
        except Exception as e:  # noqa: BLE001 - 网络/代理异常一律降级
            logger.warning("CoinGlass request failed (%s): %s", path, e)
            return None
        if resp.status_code != 200:
            logger.warning("CoinGlass HTTP %s for %s: %s", resp.status_code, path, resp.text[:200])
            return None
        try:
            payload = resp.json()
        except ValueError:
            logger.warning("CoinGlass non-JSON response for %s", path)
            return None
        if isinstance(payload, dict):
            code = str(payload.get("code", "0"))
            if code not in ("0", "200"):
                logger.warning("CoinGlass error code=%s msg=%s", code, payload.get("msg"))
                return None
            return payload.get("data", payload)
        return payload

    def coin_metrics(self) -> dict[str, dict[str, float | None]]:
        """``{COIN: {oi_change_pct, funding_rate}}``；带 TTL 缓存，失败/无 key 返回空。"""
        if not self._api_key:
            return {}
        now = time.monotonic()
        if self._cache and (now - self._cache_ts) < self._ttl:
            return self._cache
        data = self._get(_COINS_MARKETS_PATH)
        rows: list[dict[str, Any]]
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict) and isinstance(data.get("list"), list):
            rows = [r for r in data["list"] if isinstance(r, dict)]
        else:
            rows = []
        if not rows:
            return self._cache  # 失败时沿用上次缓存（可能为空）
        metrics = normalize_coin_metrics(rows)
        if metrics and not any(
            v.get("oi_change_pct") is not None or v.get("funding_rate") is not None for v in metrics.values()
        ):
            logger.debug(
                "CoinGlass coins-markets parsed but no oi_change/funding fields matched; sample keys=%s",
                list(rows[0].keys())[:20],
            )
        self._cache = metrics
        self._cache_ts = now
        return metrics


def build_coinglass_client(settings: Settings) -> CoinglassClient | None:
    """key 为空返回 None（功能关闭）。"""
    if not settings.coinglass_enabled():
        return None
    return CoinglassClient(settings)
