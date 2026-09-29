"""Adapters chosen by settings, shared by the app (``identity.main``) and the operator's
``identity-admin``, which must not build the app to reach them."""

from identity.domain.provider import IdentityProvider
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.infrastructure.providers.supabase import SupabaseIdentityProvider
from identity.settings import IdentitySettings


def identity_provider(settings: IdentitySettings) -> IdentityProvider:
    """The provider ``CW_AUTH_PROVIDER`` names; the settings have checked its configuration."""
    if settings.auth_provider == "supabase":
        if settings.supabase_service_role_key is None:  # pragma: no cover - refused by settings
            raise ValueError("CW_AUTH_PROVIDER=supabase needs CW_SUPABASE_SERVICE_ROLE_KEY")
        return SupabaseIdentityProvider(
            settings.supabase_url,
            settings.supabase_service_role_key,
            jwt_secret=settings.supabase_jwt_secret,
        )
    secret = settings.identity_fake_provider_secret
    shared = secret.get_secret_value().encode("utf-8") if secret is not None else None
    return FakeIdentityProvider(shared or None)
