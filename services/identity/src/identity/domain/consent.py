"""Consent records: who agreed to what, under which version of the notice, and when.

Append-only. A withdrawal is a record with ``granted`` false; the latest record per subject
and purpose is the current state. A grant carries the ``notice_version`` the person saw, so
a changed notice is a new consent, never a silent edit (docs/legal/consent-record.md).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from domain_kernel._validation import require_aware, require_bool, require_instance, require_text
from domain_kernel.ids import ConsentId, TenantId, UserId


class ConsentPurpose(StrEnum):
    TERMS = "terms"
    PRIVACY_NOTICE = "privacy_notice"
    PROFILE_PROCESSING = "profile_processing"
    WHATSAPP_REMINDERS = "whatsapp_reminders"
    EMAIL_REMINDERS = "email_reminders"
    ANALYTICS = "analytics"


class ConsentSource(StrEnum):
    WEB_ONBOARDING = "web_onboarding"
    WHATSAPP_KEYWORD = "whatsapp_keyword"
    API = "api"
    SUPPORT = "support"
    WEB_SETTINGS = "web_settings"
    """Changed later on the web settings pages, not at onboarding."""


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    id: ConsentId
    tenant_id: TenantId
    subject: str
    """A user id as text, or an E.164 number for a WhatsApp opt-in before the number is linked."""
    purpose: ConsentPurpose
    granted: bool
    source: ConsentSource
    recorded_at: datetime
    notice_version: str = ""
    evidence: str = ""
    recorded_by: UserId | None = None

    def __post_init__(self) -> None:
        require_instance(self.id, ConsentId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_text(self.subject, "subject")
        require_instance(self.purpose, ConsentPurpose, "purpose")
        require_bool(self.granted, "granted")
        require_instance(self.source, ConsentSource, "source")
        require_aware(self.recorded_at, "recorded_at")
        require_instance(self.notice_version, str, "notice_version")
        require_instance(self.evidence, str, "evidence")
        if self.recorded_by is not None:
            require_instance(self.recorded_by, UserId, "recorded_by")


@dataclass(frozen=True, slots=True)
class ConsentState:
    """The current answer for one purpose and how it was reached."""

    purpose: ConsentPurpose
    granted: bool
    notice_version: str
    since: datetime
    source: ConsentSource


class ConsentRepository(Protocol):
    def add(self, record: ConsentRecord) -> None: ...

    def history(self, subject: str, purpose: ConsentPurpose | None = None) -> list[ConsentRecord]:
        """Oldest first."""
        ...

    def all(self) -> list[ConsentRecord]:
        """Every record of the unit of work's tenant, oldest first (an export)."""
        ...
