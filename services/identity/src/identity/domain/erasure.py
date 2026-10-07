"""Identity's part of a tenant's erasure, and what it needs to complete the request.

When the flag ``identity.tenant_erasure`` is on for the tenant, identity's consumer of
``tenant.deletion.requested`` (group ``identity.erasure``) first deletes every user's account at
the identity provider (an account already gone counts as deleted, so a redelivery is safe), then
in one transaction (``IdentityEraser``):

- deletes the tenant's users (``app_user``), their sign-in subjects (``user_subject``) and its
  idempotency keys;
- pseudonymises its consent records under ``app.erasure`` (the only change the table's trigger
  lets through): the subject becomes ``pseudonym(tenant, subject)``, the evidence is emptied and
  ``recorded_by`` is nulled, so the record still proves that consent was given or withdrawn and
  when, but no longer whose;
- pseudonymises the billing customer's email address and name, keeping the provider's ids, the
  subscriptions and the masked webhook ledger for the tax records (for the lawyer to confirm);
- keeps the data requests, the record that the request was made and answered;
- empties the tenant's name and marks it ``erased``, so nobody signs in to it again.

It then emits ``tenant.data.erased`` (service identity) with its ``tenant.erased`` audit entry.
Identity's consumer of ``tenant.data.erased`` (group ``identity.erasure-records``) records each
service's answer on the deletion request, which completes once ``ERASURE_SERVICES`` (or
``CW_IDENTITY_ERASURE_SERVICES``) have all answered.
"""

import hashlib
from typing import Final, Protocol

from domain_kernel.erasure import Erased, TenantEraser
from domain_kernel.ids import TenantId

ERASURE_SERVICES: Final = (
    "applicability-engine",
    "identity",
    "notification",
    "obligation",
    "profile",
    "rulebook",
)
"""The services a deletion request waits for by default: each answers ``tenant.data.erased``."""
PSEUDONYM_PREFIX: Final = "erased:"
PSEUDONYM_HEX_CHARS: Final = 16


def pseudonym(tenant_id: TenantId, value: str) -> str:
    """``erased:`` and the first 16 hex digits of sha256(tenant|value): the same value of one
    tenant always gives the same pseudonym, so records stay grouped, and nothing leads back to
    the value without it. A value already pseudonymised stays as it is."""
    if value.startswith(PSEUDONYM_PREFIX):
        return value
    digest = hashlib.sha256(f"{tenant_id}|{value}".encode()).hexdigest()
    return PSEUDONYM_PREFIX + digest[:PSEUDONYM_HEX_CHARS]


class IdentityEraser(TenantEraser, Protocol):
    """Identity's erasure in the transaction its consumer commits. ``erase`` does everything the
    module docstring lists after the provider's deletions and answers the counts."""

    def erase(self, tenant_id: TenantId) -> Erased: ...
