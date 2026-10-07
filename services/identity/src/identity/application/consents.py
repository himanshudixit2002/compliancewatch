"""Record a consent or a withdrawal, and answer what a subject has agreed to.

Recording writes a ``consent.recorded`` audit entry in the same unit of work, by the request's
caller (``py_common.audit.audit_actor``): the purpose, whether it was granted, the source and the
notice version. The subject (a user id, or a phone number the log masks) is the entry's subject.

``ConsentStatus`` may also be asked whether an address on a channel is the subject's own
(``address_matches``), which the notification service asks before it records a web opt-in: True
or False when the subject is a user of the tenant with a contact on that channel (the phone for
WhatsApp, the email for email), None when identity knows none. It says only whether they match,
never the contact itself.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from domain_kernel.events import utc_now
from domain_kernel.ids import ConsentId, TenantId, UserId
from identity.application.audit import audit_entry
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource, ConsentState
from identity.domain.errors import NoticeVersionRequiredError
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.tenancy import User

ADDRESS_CHANNELS: Final = ("whatsapp", "email")
"""The channels whose address ``ConsentStatus`` compares with a user's contact."""


@dataclass(frozen=True, slots=True)
class ConsentSummary:
    subject: str
    states: tuple[ConsentState, ...]
    history: tuple[ConsentRecord, ...]
    address_matches: bool | None = None

    def granted(self, purpose: ConsentPurpose) -> bool:
        return any(state.purpose is purpose and state.granted for state in self.states)


class RecordConsent:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        subject: str,
        purpose: ConsentPurpose,
        *,
        granted: bool,
        source: ConsentSource,
        notice_version: str = "",
        evidence: str = "",
        recorded_by: UserId | None = None,
    ) -> ConsentRecord:
        if granted and not notice_version.strip():
            raise NoticeVersionRequiredError(purpose.value)
        record = ConsentRecord(
            id=ConsentId.new(),
            tenant_id=tenant_id,
            subject=subject,
            purpose=purpose,
            granted=granted,
            source=source,
            recorded_at=self._clock(),
            notice_version=notice_version.strip(),
            evidence=evidence,
            recorded_by=recorded_by,
        )
        with self._unit_of_work(tenant_id) as uow:
            uow.consents.add(record)
            uow.audit.write(
                audit_entry(
                    "consent.recorded",
                    tenant_id=tenant_id,
                    subject_type="consent",
                    subject_id=str(record.id),
                    at=record.recorded_at,
                    after={
                        "subject": record.subject,
                        "purpose": record.purpose.value,
                        "granted": record.granted,
                        "source": record.source.value,
                        "notice_version": record.notice_version,
                    },
                )
            )
        return record


class ConsentStatus:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self, tenant_id: TenantId, subject: str, *, channel: str = "", address: str = ""
    ) -> ConsentSummary:
        """The subject's consents; with ``channel`` and ``address``, also whether that address
        is the subject's own contact on the channel."""
        matches = None
        with self._unit_of_work(tenant_id) as uow:
            history = tuple(uow.consents.history(subject))
            if channel and address:
                matches = address_matches(_user(uow, subject), channel, address)
        latest: dict[ConsentPurpose, ConsentRecord] = {}
        for record in history:
            latest[record.purpose] = record
        states = tuple(
            ConsentState(
                purpose=record.purpose,
                granted=record.granted,
                notice_version=record.notice_version,
                since=record.recorded_at,
                source=record.source,
            )
            for record in latest.values()
        )
        return ConsentSummary(subject, states, history, matches)


def _user(uow: UnitOfWork, subject: str) -> User | None:
    """The tenant's user the subject names, when it is a user id; None otherwise."""
    try:
        user_id = UserId(UUID(subject))
    except ValueError:
        return None
    return uow.users.get(user_id)


def address_matches(user: User | None, channel: str, address: str) -> bool | None:
    """Whether ``address`` is the user's contact on ``channel``: the phone number for WhatsApp
    (digits compared, so ``+91 98...`` and ``9198...`` agree), the email address for email
    (case aside). None when identity knows no such contact (no user, another channel, or none
    recorded)."""
    if user is None or channel not in ADDRESS_CHANNELS:
        return None
    if channel == "whatsapp":
        known = _digits(user.contact.phone)
        return None if not known else _digits(address) == known
    known = user.contact.email.strip().lower()
    return None if not known else address.strip().lower() == known


def _digits(text: str) -> str:
    return "".join(character for character in text if character.isdigit())
