"""The composition root: what ``build_app`` logs once the app exists."""

import json
from collections.abc import Callable

import pytest
from fastapi import FastAPI

AppFactory = Callable[..., FastAPI]


def test_gateway_wired_is_logged_as_json_with_the_service_field(
    make_app: AppFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    make_app(log_json=True, log_level="INFO")
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if "gateway_wired" in line
    ]
    [line] = lines
    assert line["event"] == "gateway_wired"
    assert line["service"] == "llm-gateway"
    assert line["level"] == "info"
    assert (line["provider"], line["ledger"], line["cache"], line["langfuse"]) == (
        "fake",
        "memory",
        True,
        False,
    )
    assert (line["prompts"], line["routes"], line["providers"]) == (3, 6, 2)


def test_gateway_wired_reports_a_disabled_cache(
    make_app: AppFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    make_app(log_json=True, log_level="INFO", llm_cache_ttl_seconds=0)
    [line] = [json.loads(s) for s in capsys.readouterr().out.splitlines() if "gateway_wired" in s]
    assert line["cache"] is False
