"""强化学习子包（可选依赖 gymnasium/SB3），懒加载 FuturesPerpBarEnv。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binance_auto_ai.rl.futures_perp_env import FuturesPerpBarEnv as FuturesPerpBarEnv

__all__ = ["FuturesPerpBarEnv"]


def __getattr__(name: str):  # PEP 562 惰性导入 — 避免 ``import binance_auto_ai.rl`` 时加载 gymnasium
    if name == "FuturesPerpBarEnv":
        from binance_auto_ai.rl.futures_perp_env import FuturesPerpBarEnv as _E

        return _E
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
