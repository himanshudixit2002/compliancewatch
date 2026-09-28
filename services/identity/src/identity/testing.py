"""Builders for tests of this service."""

from typing import Any

from identity.settings import IdentitySettings


def identity_settings(**overrides: Any) -> IdentitySettings:
    """Settings that ignore the repo ``.env``; the memory store and memory billing by default."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "identity",
        "identity_store": "memory",
        "billing_provider": "memory",
    }
    values.update(overrides)
    return IdentitySettings(**values)
