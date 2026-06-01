from __future__ import annotations


def test_package_version() -> None:
    import binance_auto_ai

    assert isinstance(binance_auto_ai.__version__, str)


def test_cli_main_importable() -> None:
    from binance_auto_ai.cli import main

    assert callable(main)
