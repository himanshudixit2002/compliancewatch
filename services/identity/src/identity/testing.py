"""Builders for tests of this service."""

from typing import Any

from identity.settings import IdentitySettings

CHANNEL_TOKEN = "test-channel-token"
"""The service token ``identity_settings`` configures; send it as ``x-cw-service-token``."""


def identity_settings(**overrides: Any) -> IdentitySettings:
    """Settings that ignore the repo ``.env``: the memory store, memory billing and
    ``CHANNEL_TOKEN`` by default."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "identity",
        "identity_store": "memory",
        "billing_provider": "memory",
        "identity_channel_token": CHANNEL_TOKEN,
    }
    values.update(overrides)
    return IdentitySettings(**values)
