"""Verified identities: access tokens, the principal they name, and how services check them.

- ``keys``: ES256 signing keys, ``KeySet`` and its public JWKS, ``load_signing_keys``.
- ``tokens``: ``TokenIssuer`` (the identity service's), ``TokenVerifier`` and the key sources
  ``JwksUrlSource`` (cached) and ``StaticKeySource``.
- ``errors``: the 401, 403 and 503 problems, mapped for every service by py-common.
- ``context``: ``current_principal`` and ``bind_principal``, which names the actor in the logs.
- ``fastapi``: ``Authenticator`` by ``CW_AUTH_MODE``, the ``authenticate`` dependency,
  ``tenant_scope``, ``require_roles`` and ``shared_token_or_roles``.
- ``testing``: ``TestIssuer``, tokens signed with a key generated at run time.

This module exports only the parts without FastAPI, so an application layer can import it; import
``py_common.auth.fastapi`` and ``py_common.auth.testing`` from their own modules.
"""

from py_common.auth.context import (
    bind_actor,
    bind_principal,
    current_principal,
    principal_bound,
    principal_or_anonymous,
    unbind_principal,
)
from py_common.auth.errors import (
    AuthForbiddenError,
    AuthKeysUnavailableError,
    AuthTenantMismatchError,
    AuthTokenInvalidError,
    AuthTokenRequiredError,
)
from py_common.auth.keys import (
    ALGORITHM,
    KeySet,
    SigningKey,
    generate_signing_key,
    load_signing_keys,
)
from py_common.auth.tokens import (
    IssuedToken,
    JwksUrlSource,
    KeySource,
    StaticKeySource,
    TokenIssuer,
    TokenVerifier,
    claims_of,
    principal_from_claims,
)

__all__ = [
    "ALGORITHM",
    "AuthForbiddenError",
    "AuthKeysUnavailableError",
    "AuthTenantMismatchError",
    "AuthTokenInvalidError",
    "AuthTokenRequiredError",
    "IssuedToken",
    "JwksUrlSource",
    "KeySet",
    "KeySource",
    "SigningKey",
    "StaticKeySource",
    "TokenIssuer",
    "TokenVerifier",
    "bind_actor",
    "bind_principal",
    "claims_of",
    "current_principal",
    "generate_signing_key",
    "load_signing_keys",
    "principal_bound",
    "principal_from_claims",
    "principal_or_anonymous",
    "unbind_principal",
]
