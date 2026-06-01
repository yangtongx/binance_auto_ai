"""CoinGlass V4 数据（可选）：衍生品选币 + 链上/流向告警。

- base: https://open-api-v4.coinglass.com ，鉴权头 ``CG-API-KEY``。
- 选币：``/api/futures/coins-markets`` 聚合 OI 变化与资金费率。
- 告警：``/api/spot/netflow-list``、``/api/exchange/balance/list``、``/api/chain/v2/whale-transfer``。
- 全程「可选 + 失败降级」：未装 requests / key 为空 / 请求失败 / 字段缺失 → 返回空，
  不影响主流程。

字段名按 CoinGlass 实际返回容错解析（V4 字段可能随版本调整）；解析不到会记 debug 日志。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from binance_auto_ai.config import Settings
from binance_auto_ai.exchange_env import normalize_proxy_url, resolve_binance_proxy

logger = logging.getLogger(__name__)

_COINS_MARKETS_PATH = "/api/futures/coins-markets"
_SPOT_NETFLOW_PATH = "/api/spot/netflow-list"
_EXCHANGE_BALANCE_PATH = "/api/exchange/balance/list"
_WHALE_TRANSFER_PATH = "/api/chain/v2/whale-transfer"

_NETFLOW_24H_KEYS = ("net_flow_usd_24h", "netFlowUsd24h", "net_flow_24h")
_NETFLOW_1H_KEYS = ("net_flow_usd_1h", "netFlowUsd1h", "net_flow_1h")
_NETFLOW_4H_KEYS = ("net_flow_usd_4h", "netFlowUsd4h", "net_flow_4h")

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


def _rows_from_data(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict) and isinstance(data.get("list"), list):
        return [r for r in data["list"] if isinstance(r, dict)]
    return []


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


def normalize_spot_netflow(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    """现货净流入/流出（USD）；负值=净卖出占优。"""
    out: dict[str, dict[str, float | None]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = _row_symbol(row)
        if not sym:
            continue
        nf24 = _pick(row, _NETFLOW_24H_KEYS, substrs=("net", "flow", "24"))
        nf1 = _pick(row, _NETFLOW_1H_KEYS, substrs=("net", "flow", "1h"))
        if nf1 is None:
            nf1 = _pick(row, (), substrs=("net", "flow", "1"))
        nf4 = _pick(row, _NETFLOW_4H_KEYS, substrs=("net", "flow", "4"))
        out[sym] = {"net_flow_24h_usd": nf24, "net_flow_1h_usd": nf1, "net_flow_4h_usd": nf4}
    return out


def normalize_exchange_balance(rows: list[dict[str, Any]]) -> list[dict[str, float | str | None]]:
    """各交易所储备及 24h 变化；``balance_change_percent_1d`` 为正=币流入交易所。"""
    out: list[dict[str, float | str | None]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("exchange_name") or row.get("exchangeName") or row.get("exchange")
        if not isinstance(name, str) or not name.strip():
            continue
        pct = _pick(
            row,
            ("balance_change_percent_1d", "balanceChangePercent1d", "change_percent_1d"),
            substrs=("change", "percent", "1d"),
        )
        bal_chg = _pick(
            row,
            ("balance_change_1d", "balanceChange1d", "change_1d"),
            substrs=("change", "1d"),
        )
        total = _pick(row, ("total_balance", "totalBalance", "balance"), substrs=("total", "balance"))
        out.append(
            {
                "exchange_name": name.strip(),
                "balance_change_percent_1d": pct,
                "balance_change_1d": bal_chg,
                "total_balance": total,
            }
        )
    return out


def normalize_whale_transfer(row: dict[str, Any]) -> dict[str, object] | None:
    tx = row.get("transaction_hash") or row.get("transactionHash") or row.get("hash")
    if not isinstance(tx, str) or not tx.strip():
        return None
    amount = _as_float(row.get("amount_usd") or row.get("amountUsd") or row.get("amountUSD"))
    qty = _as_float(row.get("asset_quantity") or row.get("assetQuantity"))
    asset = row.get("asset_symbol") or row.get("assetSymbol") or row.get("symbol")
    frm = row.get("from") or row.get("fromAddress") or row.get("from_address")
    to = row.get("to") or row.get("toAddress") or row.get("to_address")
    chain = row.get("blockchain_name") or row.get("blockchainName") or row.get("blockchain")
    ts = row.get("block_timestamp") or row.get("blockTimestamp") or row.get("timestamp")
    ts_f = _as_float(ts)
    coin = row.get("coin") or row.get("base")
    if isinstance(coin, str):
        coin = coin.strip().upper()
    else:
        coin = None
    if isinstance(asset, str):
        asset = asset.strip().upper()
    else:
        asset = None
    return {
        "transaction_hash": tx.strip(),
        "amount_usd": amount,
        "asset_quantity": qty,
        "asset_symbol": asset,
        "coin": coin,
        "from": str(frm) if frm is not None else "",
        "to": str(to) if to is not None else "",
        "blockchain": str(chain) if chain is not None else "",
        "block_timestamp": int(ts_f) if ts_f is not None else None,
    }


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
        self._netflow_cache_ts = 0.0
        self._netflow_cache: dict[str, dict[str, float | None]] = {}
        self._balance_cache: dict[str, tuple[float, list[dict[str, float | str | None]]]] = {}
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
        rows = _rows_from_data(data)
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

    def spot_netflow(self) -> dict[str, dict[str, float | None]]:
        """``{COIN: {net_flow_24h_usd, net_flow_1h_usd, net_flow_4h_usd}}``。"""
        if not self._api_key:
            return {}
        now = time.monotonic()
        if self._netflow_cache and (now - self._netflow_cache_ts) < self._ttl:
            return self._netflow_cache
        data = self._get(_SPOT_NETFLOW_PATH, {"page": 1, "per_page": 500})
        rows = _rows_from_data(data)
        if not rows:
            return self._netflow_cache
        metrics = normalize_spot_netflow(rows)
        self._netflow_cache = metrics
        self._netflow_cache_ts = now
        return metrics

    def exchange_balance(self, coin: str) -> list[dict[str, float | str | None]]:
        """某币在各交易所的储备及 24h 变化。"""
        if not self._api_key:
            return []
        key = coin.strip().upper()
        if not key:
            return []
        now = time.monotonic()
        cached = self._balance_cache.get(key)
        if cached and (now - cached[0]) < self._ttl:
            return cached[1]
        data = self._get(_EXCHANGE_BALANCE_PATH, {"symbol": key})
        rows = _rows_from_data(data)
        if not rows:
            return cached[1] if cached else []
        parsed = normalize_exchange_balance(rows)
        self._balance_cache[key] = (now, parsed)
        return parsed

    def whale_transfers(
        self,
        coin: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> list[dict[str, object]]:
        """某币在时间段内的大额链上转账（≥$10M，CoinGlass 口径）。"""
        if not self._api_key:
            return []
        key = coin.strip().upper()
        if not key:
            return []
        data = self._get(
            _WHALE_TRANSFER_PATH,
            {"symbol": key, "start_time": str(start_ms), "end_time": str(end_ms)},
        )
        rows = _rows_from_data(data)
        out: list[dict[str, object]] = []
        for row in rows:
            parsed = normalize_whale_transfer(row)
            if parsed is not None:
                out.append(parsed)
        return out


def build_coinglass_client(settings: Settings) -> CoinglassClient | None:
    """key 为空返回 None（功能关闭）。"""
    if not settings.coinglass_enabled():
        return None
    return CoinglassClient(settings)
