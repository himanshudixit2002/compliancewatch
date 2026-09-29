"""Process configuration of the identity service: ``CW_*`` on top of py-common's.

Nothing here creates an account. ``identity_store`` picks memory or postgres for consent
records. Billing stays ``none`` until the maintainer has a Razorpay account, plans and keys
(docs in identity/infrastructure/billing/razorpay.py); ``razorpay_plan_ids`` maps our plan
keys to Razorpay plan ids as ``owner_monthly=plan_x,ca_seat_monthly=plan_y``.

``identity_channel_token`` is the shared secret the WhatsApp bot sends in
``x-cw-service-token`` to record and read channel consents. Unset, both routes refuse every call
(503): consents keyed by a phone number are personal data no tenant guards, so they fail closed.

``auth_provider`` picks the identity provider people sign in with (``CW_AUTH_PROVIDER``; owner
identity-partner): ``fake`` (the default) signs provider tokens in the process, with
``identity_fake_provider_secret`` when several dev processes must accept each other's tokens;
``supabase`` verifies Supabase Auth tokens and manages accounts with ``supabase_url`` and
``supabase_service_role_key`` (``supabase_jwt_secret`` only for a project still on the legacy
HS256 secret). Production refuses ``fake``.
"""

from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from py_common.settings import Settings

MIN_FAKE_SECRET_BYTES = 32
Store = Literal["memory", "postgres"]
Billing = Literal["none", "memory", "razorpay"]
AuthProvider = Literal["fake", "supabase"]


class IdentitySettings(Settings):
    identity_store: Store = "postgres"
    billing_provider: Billing = "none"
    razorpay_key_id: str = ""
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None
    razorpay_plan_ids: dict[str, str] = Field(default_factory=dict)
    identity_channel_token: SecretStr | None = None
    auth_provider: AuthProvider = "fake"
    identity_fake_provider_secret: SecretStr | None = None
    supabase_url: str = ""
    supabase_service_role_key: SecretStr | None = None
    supabase_jwt_secret: SecretStr | None = None

    @field_validator("razorpay_plan_ids", mode="before")
    @classmethod
    def _parse_plan_ids(cls, value: object) -> object:
        if isinstance(value, str):
            pairs = [item.split("=", 1) for item in value.split(",") if "=" in item]
            return {key.strip(): plan_id.strip() for key, plan_id in pairs}
        return value

    @model_validator(mode="after")
    def _check_the_provider(self) -> Self:
        if self.auth_provider == "fake" and self.env == "prod":
            raise ValueError(
                "CW_ENV=prod needs CW_AUTH_PROVIDER=supabase: the fake provider signs anyone in"
            )
        if self.auth_provider == "supabase" and (
            not self.supabase_url or not _secret(self.supabase_service_role_key)
        ):
            raise ValueError(
                "CW_AUTH_PROVIDER=supabase needs CW_SUPABASE_URL and CW_SUPABASE_SERVICE_ROLE_KEY"
            )
        secret = _secret(self.identity_fake_provider_secret)
        if secret and len(secret.encode("utf-8")) < MIN_FAKE_SECRET_BYTES:
            raise ValueError(
                f"CW_IDENTITY_FAKE_PROVIDER_SECRET needs at least {MIN_FAKE_SECRET_BYTES} bytes"
            )
        return self


def _secret(value: SecretStr | None) -> str:
    return "" if value is None else value.get_secret_value()
