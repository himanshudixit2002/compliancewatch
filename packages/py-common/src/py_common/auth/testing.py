"""Access tokens for tests, signed with a key made when the issuer is built.

Nothing is committed: every ``TestIssuer`` generates its own P-256 key, so no private key sits in
the repository. A test builds the service with ``issuer.settings_overrides("token")``, which puts
the issuer's JWKS inline, and calls it with ``bearer(issuer.user(tenant, [Role.OWNER]))``::

    issuer = TestIssuer()
    settings = ProfileSettings(_env_file=None, **issuer.settings_overrides("token"))
    client.get(path, headers=bearer(issuer.user(tenant, [Role.OWNER])))
"""

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any, Final

from domain_kernel.access import Principal, Role, Scope
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId, UserId
from py_common.auth.keys import KeySet, generate_signing_key
from py_common.auth.tokens import IssuedToken, StaticKeySource, TokenIssuer, TokenVerifier
from py_common.settings import AuthMode, Settings

DEFAULT_TTL: Final = timedelta(minutes=10)


def bearer(token: str) -> dict[str, str]:
    """The ``Authorization`` header that carries ``token``."""
    return {"Authorization": f"Bearer {token}"}


class TestIssuer:
    """Issues tokens the way the identity service does, for the issuer and audience the settings
    default to, with a key generated at construction."""

    __test__ = False  # not a pytest test class, although its name starts with Test

    def __init__(
        self,
        *,
        kid: str = "test-key",
        issuer: str | None = None,
        audience: str | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        fields = Settings.model_fields
        self.issuer_name = issuer or str(fields["auth_issuer"].default)
        self.audience = audience or str(fields["auth_audience"].default)
        self.keys = KeySet((generate_signing_key(kid),))
        self._issuer = TokenIssuer(
            self.keys, issuer=self.issuer_name, audience=self.audience, clock=clock
        )

    def issue(self, principal: Principal, ttl: timedelta = DEFAULT_TTL) -> IssuedToken:
        return self._issuer.issue(principal, ttl)

    def user(
        self,
        tenant: TenantId,
        roles: Iterable[Role] = (Role.OWNER,),
        *,
        mfa: bool = False,
        user_id: UserId | None = None,
        session_version: int = 0,
        ttl: timedelta = DEFAULT_TTL,
    ) -> str:
        """A user's token for ``tenant``; a new user id unless one is given."""
        principal = Principal.user(
            user_id or UserId.new(), tenant, roles, mfa=mfa, session_version=session_version
        )
        return self.issue(principal, ttl).token

    def service(
        self, client_id: str, scopes: Iterable[Scope], *, ttl: timedelta = DEFAULT_TTL
    ) -> str:
        """A service client's token holding ``scopes``."""
        return self.issue(Principal.service(client_id, scopes), ttl).token

    def jwks(self) -> dict[str, Any]:
        return self.keys.public_jwks()

    def jwks_json(self) -> str:
        """The public key set, as ``CW_AUTH_JWKS_JSON`` takes it."""
        return json.dumps(self.jwks())

    def verifier(self) -> TokenVerifier:
        return TokenVerifier(
            StaticKeySource.from_key_set(self.keys), issuer=self.issuer_name, audience=self.audience
        )

    def settings_overrides(self, mode: AuthMode = "token") -> dict[str, Any]:
        """Settings fields that make a service verify this issuer's tokens in ``mode``."""
        return {
            "auth_mode": mode,
            "auth_jwks_json": self.jwks_json(),
            "auth_issuer": self.issuer_name,
            "auth_audience": self.audience,
        }
