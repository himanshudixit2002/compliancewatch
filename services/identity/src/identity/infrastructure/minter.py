"""The token minter: the use cases' port onto py-common's ES256 ``TokenIssuer``."""

from datetime import timedelta

from domain_kernel.access import Principal
from identity.domain.sessions import MAX_TTL, MIN_TTL, AccessToken
from py_common.auth import TokenIssuer


class IssuerMinter:
    """Signs access tokens with the identity service's first signing key."""

    def __init__(self, issuer: TokenIssuer) -> None:
        self._issuer = issuer

    def mint(self, principal: Principal, ttl: timedelta) -> AccessToken:
        if not MIN_TTL <= ttl <= MAX_TTL:
            raise ValueError(f"an access token lives between {MIN_TTL} and {MAX_TTL}, got {ttl}")
        issued = self._issuer.issue(principal, ttl)
        return AccessToken(
            token=issued.token, expires_at=issued.expires_at, expires_in=int(ttl.total_seconds())
        )
