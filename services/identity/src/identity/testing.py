"""Builders for tests of this service, and of others that sign in through it.

The signing key, the fake provider's secret and the dev client secret are made when this module
is imported, so nothing secret is committed and every app a test process builds with
``identity_settings`` signs and verifies with the same key.
"""

import secrets
from typing import Any, Final

from identity.settings import IdentitySettings
from py_common.auth import KeySet, generate_signing_key

CHANNEL_TOKEN = "test-channel-token"
"""The service token ``identity_settings`` configures; send it as ``x-cw-service-token``."""
SIGNING_KEYS: Final = KeySet((generate_signing_key("identity-test"),))
"""The key set every app built with ``identity_settings`` signs with."""
FAKE_PROVIDER_SECRET: Final = secrets.token_urlsafe(32)
"""The fake provider's secret: ``FakeIdentityProvider(FAKE_PROVIDER_SECRET.encode())`` signs
provider tokens these apps accept."""
DEV_CLIENT_SECRET: Final = secrets.token_urlsafe(32)
"""The secret of every dev service client (the committed ``identity_dev_clients.toml``)."""


def identity_settings(**overrides: Any) -> IdentitySettings:
    """Settings that ignore the repo ``.env``: the memory store, memory billing,
    ``CHANNEL_TOKEN``, the fake provider with ``FAKE_PROVIDER_SECRET``, ``SIGNING_KEYS`` and the
    dev clients with ``DEV_CLIENT_SECRET``, in header mode unless ``auth_mode`` says otherwise."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "identity",
        "identity_store": "memory",
        "billing_provider": "memory",
        "identity_channel_token": CHANNEL_TOKEN,
        "auth_provider": "fake",
        "identity_fake_provider_secret": FAKE_PROVIDER_SECRET,
        "identity_signing_keys": SIGNING_KEYS.dumps(),
        "identity_dev_client_secret": DEV_CLIENT_SECRET,
    }
    values.update(overrides)
    return IdentitySettings(**values)
