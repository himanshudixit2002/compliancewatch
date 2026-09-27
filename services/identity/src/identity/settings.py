"""Process configuration of the identity service: ``CW_*`` on top of py-common's.

Nothing here creates an account. ``identity_store`` picks memory or postgres for consent
records. Billing stays ``none`` until the maintainer has a Razorpay account, plans and keys
(docs in identity/infrastructure/billing/razorpay.py); ``razorpay_plan_ids`` maps our plan
keys to Razorpay plan ids as ``owner_monthly=plan_x,ca_seat_monthly=plan_y``.
"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator

from py_common.settings import Settings

Store = Literal["memory", "postgres"]
Billing = Literal["none", "memory", "razorpay"]


class IdentitySettings(Settings):
    identity_store: Store = "postgres"
    billing_provider: Billing = "none"
    razorpay_key_id: str = ""
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None
    razorpay_plan_ids: dict[str, str] = Field(default_factory=dict)

    @field_validator("razorpay_plan_ids", mode="before")
    @classmethod
    def _parse_plan_ids(cls, value: object) -> object:
        if isinstance(value, str):
            pairs = [item.split("=", 1) for item in value.split(",") if "=" in item]
            return {key.strip(): plan_id.strip() for key, plan_id in pairs}
        return value
