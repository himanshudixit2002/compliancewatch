"""What the audit log keeps of an entry: the entry masked for personal identifiers.

``masked_entry(entry)`` is ``entry`` with its reason, and every text of ``before`` and ``after`` at
any depth, masked with the patterns log lines are masked with (``domain_kernel.pii.mask_pii_in``):
GSTINs, PANs, Aadhaar numbers, phone numbers and email addresses become ``[GSTIN]``, ``[PAN]``,
``[AADHAAR]``, ``[PHONE]`` and ``[EMAIL]``. A UUID in its canonical form and a lower-case hex id of
16 or more (a SHA-256 digest) are kept whole wherever they stand, and the value of a key ending in
``_id`` or ``_ids`` is left alone, since a twelve-digit piece of an id would read as an Aadhaar
number. The action, the subject and its id, the actor and the correlation id are never masked:
they say who did what to which record.

The Postgres writer (``writer.audit_row``) and the memory twin (``MemoryAuditSink``) both store
what it returns, so the tests of a service on its memory store see the row a database would hold.

Masking can make a reason longer (``a@b.co`` has six characters, ``[EMAIL]`` seven): a reason
that would then pass ``MAX_REASON_CHARS`` is cut, with room for what the cut brings to light, and
masked again.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Final, cast

from domain_kernel.audit import MAX_REASON_CHARS, AuditEntry
from domain_kernel.pii import mask_pii_in

_ROOM: Final = 16
"""What a cut reason leaves free: masking the identifier a cut may complete can lengthen it."""


def masked_entry(entry: AuditEntry) -> AuditEntry:
    """``entry`` as the audit log keeps it: its reason, ``before`` and ``after`` masked."""
    return replace(
        entry,
        reason=_masked_reason(entry.reason),
        before=_masked_state(entry.before),
        after=_masked_state(entry.after),
    )


def _masked_reason(reason: str) -> str:
    masked = mask_pii_in(reason)
    while len(masked) > MAX_REASON_CHARS:
        masked = mask_pii_in(masked[: MAX_REASON_CHARS - _ROOM])
    return masked


def _masked_state(state: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if state is None:
        return None
    # A mapping always comes back as a dict, with text keys as it had them.
    return cast(Mapping[str, object], mask_pii_in(state))
