"""Idempotency key that stops a business receiving the same notification twice."""

import hashlib
import re
from dataclasses import dataclass
from typing import Self

from domain_kernel._validation import require_instance
from domain_kernel.channels import Channel
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, RuleVersionId

_KEY_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class DedupeKey:
    """A lowercase hex SHA-256 digest."""

    value: str

    def __post_init__(self) -> None:
        text = require_instance(self.value, str, "dedupe key")
        if not _KEY_PATTERN.fullmatch(text):
            raise InvariantViolationError("dedupe key must be 64 lowercase hex characters")

    @classmethod
    def for_notification(
        cls, rule_version_id: RuleVersionId, business_id: BusinessId, channel: Channel
    ) -> Self:
        """Key for one rule version, one business and one channel."""
        material = str(rule_version_id.value) + str(business_id.value) + channel.value
        return cls(hashlib.sha256(material.encode("ascii")).hexdigest())
