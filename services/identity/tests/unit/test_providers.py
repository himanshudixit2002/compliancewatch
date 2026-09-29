"""The fake identity provider, the provider identity, and how settings pick a provider."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from domain_kernel.errors import InvariantViolationError
from identity.domain.errors import ProviderAccountExistsError, ProviderTokenInvalidError
from identity.domain.provider import AAL1, AAL2, ProviderIdentity
from identity.domain.tenancy import Contact
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.infrastructure.providers.supabase import SupabaseIdentityProvider
from identity.main import identity_provider
from identity.testing import identity_settings

SHARED_SECRET = secrets.token_hex(20)
"""A fake provider secret shared by two instances, made at run time."""
PHONE = "+919876543210"


def test_the_fake_provider_issues_tokens_it_verifies() -> None:
    issued = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=5)
    fake = FakeIdentityProvider(clock=lambda: issued + timedelta(microseconds=5))
    assert fake.name == "fake"
    identity = fake.verify(fake.issue(phone="91 98765 43210", aal=AAL2))
    assert identity.subject == FakeIdentityProvider.subject_for(Contact(phone=PHONE))
    assert (identity.phone, identity.email, identity.mfa) == (PHONE, "", True)
    assert identity.issued_at == issued
    by_email = fake.verify(fake.issue(email="Owner@Acme.Example"))
    assert (by_email.email, by_email.aal) == ("owner@acme.example", AAL1)
    assert by_email.subject != identity.subject
    assert fake.verify(fake.issue(phone=PHONE)).subject == identity.subject


def test_the_fake_provider_refuses_other_secrets_and_expired_tokens() -> None:
    fake = FakeIdentityProvider()
    other = FakeIdentityProvider()
    with pytest.raises(ProviderTokenInvalidError):
        fake.verify(other.issue(phone=PHONE))
    stale = FakeIdentityProvider(
        SHARED_SECRET.encode(), clock=lambda: datetime.now(UTC) - timedelta(hours=2)
    )
    with pytest.raises(ProviderTokenInvalidError, match="expired"):
        FakeIdentityProvider(SHARED_SECRET.encode()).verify(stale.issue(phone=PHONE))
    shared = FakeIdentityProvider(SHARED_SECRET.encode())
    assert FakeIdentityProvider(SHARED_SECRET.encode()).verify(shared.issue(phone=PHONE))
    for token in ("garbage", jwt.encode({"sub": "x"}, "k" * 32, algorithm="HS256")):
        with pytest.raises(ProviderTokenInvalidError):
            fake.verify(token)
    with pytest.raises(ValueError, match="32 bytes"):
        FakeIdentityProvider(b"short")
    with pytest.raises(ValueError, match="aal"):
        fake.issue(phone=PHONE, aal="aal3")


def test_the_fake_provider_keeps_accounts_in_the_process() -> None:
    fake = FakeIdentityProvider()
    subject = fake.provision(phone=PHONE, display_name="Ravi")
    assert subject == fake.verify(fake.issue(phone=PHONE)).subject
    found = fake.lookup(subject)
    assert found is not None
    assert found.phone == PHONE
    with pytest.raises(ProviderAccountExistsError):
        fake.provision(phone=PHONE)
    fake.delete(subject)
    fake.delete(subject)
    assert fake.lookup(subject) is None


@pytest.mark.parametrize(
    "values",
    [
        {"subject": ""},
        {"subject": "s" * 256},
        {"subject": "s", "aal": "aal3"},
        {"subject": "s", "issued_at": datetime(2026, 10, 1)},
        {"subject": "s", "email": None},
    ],
)
def test_provider_identity_invariants(values: dict[str, Any]) -> None:
    with pytest.raises(InvariantViolationError):
        ProviderIdentity(**values)


def test_settings_pick_the_provider() -> None:
    fake = identity_provider(identity_settings())
    assert isinstance(fake, FakeIdentityProvider)
    shared = identity_settings(identity_fake_provider_secret=SHARED_SECRET)
    token = FakeIdentityProvider(SHARED_SECRET.encode()).issue(phone=PHONE)
    assert identity_provider(shared).verify(token).phone == PHONE
    supabase = identity_provider(
        identity_settings(
            auth_provider="supabase",
            supabase_url="https://project-ref.supabase.test",
            supabase_service_role_key="test-service-role-value",
        )
    )
    assert isinstance(supabase, SupabaseIdentityProvider)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"env": "prod", "auth_mode": "token"}, "CW_AUTH_PROVIDER=supabase"),
        ({"auth_provider": "supabase"}, "CW_SUPABASE_URL"),
        (
            {"auth_provider": "supabase", "supabase_url": "https://x.supabase.test"},
            "CW_SUPABASE_SERVICE_ROLE_KEY",
        ),
        ({"identity_fake_provider_secret": "short"}, "32 bytes"),
    ],
)
def test_settings_refuse_an_unusable_provider(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        identity_settings(**overrides)


def test_the_secret_settings_stay_secret() -> None:
    settings = identity_settings(supabase_jwt_secret="legacy", identity_fake_provider_secret=None)
    assert isinstance(settings.supabase_jwt_secret, SecretStr)
    assert "legacy" not in repr(settings)
