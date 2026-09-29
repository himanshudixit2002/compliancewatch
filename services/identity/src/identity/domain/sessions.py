"""Sessions: the access tokens the identity service issues, behind a port.

The identity service is the only issuer every other service trusts. It exchanges a provider token
for its own access token, so services never see provider tokens and a change of provider touches
this service only (ADR-014). ``TokenMinter`` is the port the use cases mint through; the
infrastructure signs with the service's ES256 keys.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from domain_kernel._validation import require_aware, require_int, require_text
from domain_kernel.access import Principal

MIN_TTL: Final = timedelta(minutes=1)
MAX_TTL: Final = timedelta(hours=1)
"""Access tokens live between a minute and an hour; ten minutes by default. A revocation takes
effect in other services when the token expires, so the upper bound is also the longest a
revoked session can last there."""


@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    expires_at: datetime
    expires_in: int
    """Seconds from issue to expiry."""

    def __post_init__(self) -> None:
        require_text(self.token, "token")
        require_aware(self.expires_at, "expires_at")
        require_int(self.expires_in, "expires_in", minimum=1)


class TokenMinter(Protocol):
    def mint(self, principal: Principal, ttl: timedelta) -> AccessToken:
        """An access token naming ``principal`` that expires ``ttl`` from now."""
        ...
