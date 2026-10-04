"""What ``connect`` hands to ``Client.connect`` for each way of reaching Temporal."""

from typing import Any

import pytest
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import TLSConfig

from py_common.settings import Settings
from py_common.temporal.client import connect

TEMPORAL_KEY = "temporal-test-key"  # a test value, not a credential
PEM_CERT = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
PEM_KEY = "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n"


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []

    async def fake_connect(target_host: str, **kwargs: Any) -> str:
        recorded.append({"target_host": target_host, **kwargs})
        return "client"

    monkeypatch.setattr(Client, "connect", fake_connect)
    return recorded


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


async def test_the_default_is_a_plain_connection(calls: list[dict[str, Any]]) -> None:
    connected: object = await connect(settings(temporal_address="temporal:7233"))
    assert connected == "client"
    (call,) = calls
    assert call["target_host"] == "temporal:7233"
    assert call["namespace"] == "default"
    assert call["api_key"] is None
    assert call["tls"] is False
    assert call["data_converter"] is pydantic_data_converter
    assert len(call["interceptors"]) == 1


async def test_an_api_key_goes_over_tls(calls: list[dict[str, Any]]) -> None:
    await connect(
        settings(
            temporal_address="ns.acct.tmprl.cloud:7233",
            temporal_namespace="ns.acct",
            temporal_api_key=TEMPORAL_KEY,
        )
    )
    (call,) = calls
    assert call["api_key"] == TEMPORAL_KEY
    assert call["tls"] is True
    assert call["namespace"] == "ns.acct"


async def test_a_client_certificate_is_mutual_tls_with_the_pem_bytes(
    calls: list[dict[str, Any]],
) -> None:
    await connect(settings(temporal_tls_cert=PEM_CERT, temporal_tls_key=PEM_KEY))
    (call,) = calls
    assert call["api_key"] is None
    assert call["tls"] == TLSConfig(
        client_cert=PEM_CERT.encode("utf-8"), client_private_key=PEM_KEY.encode("utf-8")
    )


async def test_tls_can_be_turned_on_without_a_credential(calls: list[dict[str, Any]]) -> None:
    await connect(settings(temporal_tls=True), interceptors=[])
    (call,) = calls
    assert (call["api_key"], call["tls"], call["interceptors"]) == (None, True, [])
