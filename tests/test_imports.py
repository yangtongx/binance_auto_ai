from __future__ import annotations


def test_package_version() -> None:
    import futures_llm_bot

    assert isinstance(futures_llm_bot.__version__, str)


def test_cli_main_importable() -> None:
    from futures_llm_bot.cli import main

    assert callable(main)
