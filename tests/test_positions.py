from __future__ import annotations

from binance_auto_ai.positions import signed_position_contracts


def test_signed_position_unknown_side_does_not_use_notional_as_contracts() -> None:
    row = {"contracts": 0.01, "side": "", "notional": 500.0, "symbol": "X/Y:Z"}
    assert signed_position_contracts(row) == 0.0


def test_signed_position_long_short() -> None:
    assert signed_position_contracts({"contracts": 2.0, "side": "long"}) == 2.0
    assert signed_position_contracts({"contracts": 2.0, "side": "short"}) == -2.0
