"""The identity provider: who signs people in, behind a protocol (ADR-014).

People sign in at the provider (Supabase Auth in the MVP, a fake one in local runs and tests), which
hands them a provider token. The identity service verifies that token, looks its subject up and
issues its own access token; no other service ever sees a provider token, so replacing the provider
touches this service only.

The provider also holds the accounts: ``provision`` creates one for a person a tenant admin
invites and answers its subject, ``lookup`` reads one back, and ``delete`` removes one when a
person's data is erased.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from identity.domain.tenancy import MAX_SUBJECT_CHARS, Contact

AAL1: Final = "aal1"
"""Authenticator assurance level 1: one factor, such as a one-time code."""
AAL2: Final = "aal2"
"""Authenticator assurance level 2: a second factor was verified in this session."""
AAL_LEVELS: Final = (AAL1, AAL2)


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    """Who the provider says signed in: its subject, the verified contact and the assurance
    level of the sign-in."""

    subject: str
    email: str = ""
    phone: str = ""
    aal: str = AAL1
    issued_at: datetime | None = None

    def __post_init__(self) -> None:
        text = require_text(self.subject, "subject")
        if len(text) > MAX_SUBJECT_CHARS:
            raise InvariantViolationError(f"subject has at most {MAX_SUBJECT_CHARS} characters")
        require_instance(self.email, str, "email")
        require_instance(self.phone, str, "phone")
        if self.aal not in AAL_LEVELS:
            raise InvariantViolationError(
                f"aal must be one of {', '.join(AAL_LEVELS)}, got {self.aal!r}"
            )
        if self.issued_at is not None:
            require_aware(self.issued_at, "issued_at")

    @property
    def mfa(self) -> bool:
        """Whether the person signed in with a second factor."""
        return self.aal == AAL2

    @property
    def contact(self) -> Contact:
        """The email address and phone number in the form users keep them."""
        return Contact.of(email=self.email, phone=self.phone)


class IdentityProvider(Protocol):
    @property
    def name(self) -> str:
        """The provider's name as users record it: ``fake`` or ``supabase``."""
        ...

    def verify(self, token: str) -> ProviderIdentity:
        """The identity a provider token names. ``ProviderTokenInvalidError`` when it fails a
        check; ``ProviderUnavailableError`` when the provider's keys cannot be had, so a new
        sign-in fails closed."""
        ...

    def provision(self, *, email: str = "", phone: str = "", display_name: str = "") -> str:
        """Create the provider's account for a person and answer its subject.
        ``ProviderAccountExistsError`` when the provider has an account for the address."""
        ...

    def lookup(self, subject: str) -> ProviderIdentity | None:
        """The account the provider holds for ``subject``, or None."""
        ...

    def delete(self, subject: str) -> None:
        """Remove the provider's account for ``subject``; an account already gone is fine."""
        ...
