"""Identity's part of a tenant's erasure, and what it needs to complete the request.

When the flag ``identity.tenant_erasure`` is on for the tenant, identity's consumer of
``tenant.deletion.requested`` (group ``identity.erasure``) first checks the event against its own
records (``identity.application.erasure.CheckErasure``: the tenant asked for its deletion, is not
the internal tenant, and the event is the one sent for its open deletion request); a refused
event touches nothing. It then deletes every user's account at the identity provider (an account
already gone counts as deleted, so a redelivery is safe), then in one transaction
(``IdentityEraser``):

- deletes the tenant's users (``app_user``), their sign-in subjects (``user_subject``) and its
  idempotency keys; with the users goes every session, so a token issued before the erasure opens
  no identity route (401) and every other service answers it 410 by its erased marker;
- pseudonymises its consent records under ``app.erasure`` (the only change the table's trigger
  lets through): the subject becomes ``pseudonym(tenant, subject, pepper)``, the evidence is
  emptied and ``recorded_by`` is nulled, so the record still proves that consent was given or
  withdrawn and when, but no longer whose;
- pseudonymises the billing customer's email address and empties its name, keeping the
  provider's ids, the subscriptions and the masked webhook ledger for the tax records (for the
  lawyer to confirm), and empties the checkout links of its subscriptions and starts;
- keeps the data requests, the record that the request was made and answered;
- empties the tenant's name and marks it ``erased``, so nobody signs in to it again, and writes
  its erased marker.

It then emits ``tenant.data.erased`` (service identity) with its ``tenant.erased`` audit entry.
Identity's consumer of ``tenant.data.erased`` (group ``identity.erasure-records``) records each
service's answer on the deletion request. Once ``ERASURE_SERVICES`` (or
``CW_IDENTITY_ERASURE_SERVICES``) have all answered, it sends the request a second time
(``CW_IDENTITY_ERASURE_SECOND_PASS_SECONDS`` later, longer than an access token lives), and the
request completes once they have all answered that too: what a write in flight during the first
pass left behind goes then.
"""

import hashlib
import hmac
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
PSEUDONYM_HEX_CHARS: Final = 32


def pseudonym(tenant_id: TenantId, value: str, pepper: bytes) -> str:
    """``erased:`` and the first 32 hex digits of HMAC-SHA256 keyed with ``pepper``
    (``CW_IDENTITY_ERASURE_PEPPER``, a secret held outside the database) over ``tenant|value``.

    The same value of one tenant gives the same pseudonym under one pepper, so records stay
    grouped. Without the pepper nothing leads back to the value: a phone number or an email
    address cannot be found by trying every candidate, as an unkeyed hash allows. Whoever holds
    the pepper can still test a candidate, so this is pseudonymisation, not anonymisation, and
    counsel signs the formula off (docs/legal/data-map.md). A value already pseudonymised stays
    as it is."""
    if value.startswith(PSEUDONYM_PREFIX):
        return value
    if not pepper:
        raise ValueError("a pseudonym needs the erasure pepper")
    digest = hmac.new(pepper, f"{tenant_id}|{value}".encode(), hashlib.sha256).hexdigest()
    return PSEUDONYM_PREFIX + digest[:PSEUDONYM_HEX_CHARS]


class IdentityEraser(TenantEraser, Protocol):
    """Identity's erasure in the transaction its consumer commits. ``erase`` does everything the
    module docstring lists after the provider's deletions and answers the counts."""

    def erase(self, tenant_id: TenantId) -> Erased: ...
