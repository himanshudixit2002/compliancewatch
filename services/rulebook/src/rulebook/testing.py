"""Helpers for tests and demos that run the rulebook in process on the memory store."""

from typing import Any

from rulebook.settings import RulebookSettings

WRITE_TOKEN = "test-write-token"
"""The write token ``rulebook_settings`` configures; send it as ``x-cw-write-token``."""
REVIEW_TOKEN = "test-review-token"
"""The review token ``rulebook_settings`` configures; send it as ``x-cw-review-token``."""


def rulebook_settings(**overrides: Any) -> RulebookSettings:
    """Settings that ignore the repo ``.env``: the memory store, ``WRITE_TOKEN`` and
    ``REVIEW_TOKEN``."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "rulebook",
        "rulebook_store": "memory",
        "rulebook_write_token": WRITE_TOKEN,
        "rulebook_review_token": REVIEW_TOKEN,
    }
    values.update(overrides)
    return RulebookSettings(**values)
