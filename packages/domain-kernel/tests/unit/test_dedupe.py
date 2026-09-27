import hashlib
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, RuleVersionId

_RULE_VERSION = RuleVersionId(UUID("11111111-1111-1111-1111-111111111111"))
_BUSINESS = BusinessId(UUID("22222222-2222-2222-2222-222222222222"))
_GOLDEN = {
    Channel.WHATSAPP: "31cfe6d670a19c81972252e3a1bc8b8338b36518d109de06ca27631f423ac845",
    Channel.EMAIL: "bfc9a0f97ac462a274fe0edb3b3fd8e8f13309e97bd3918ffecc2fda41f1bdc0",
}


def _expected(rule_version_id: RuleVersionId, business_id: BusinessId, channel: Channel) -> str:
    material = str(rule_version_id.value) + str(business_id.value) + channel.value
    return hashlib.sha256(material.encode("ascii")).hexdigest()


@pytest.mark.parametrize("channel", list(Channel))
def test_golden_values_match_a_local_sha256(channel: Channel) -> None:
    expected = _expected(_RULE_VERSION, _BUSINESS, channel)
    assert expected == _GOLDEN[channel]
    assert DedupeKey.for_notification(_RULE_VERSION, _BUSINESS, channel).value == expected


def test_channel_changes_the_key() -> None:
    whatsapp = DedupeKey.for_notification(_RULE_VERSION, _BUSINESS, Channel.WHATSAPP)
    email = DedupeKey.for_notification(_RULE_VERSION, _BUSINESS, Channel.EMAIL)
    assert whatsapp != email
    assert whatsapp == DedupeKey(_GOLDEN[Channel.WHATSAPP])


@pytest.mark.parametrize(
    "value",
    [
        "",
        "31CFE6D670A19C81972252E3A1BC8B8338B36518D109DE06CA27631F423AC845",
        "31cfe6d670a19c81972252e3a1bc8b8338b36518d109de06ca27631f423ac84",
        "31cfe6d670a19c81972252e3a1bc8b8338b36518d109de06ca27631f423ac8450",
        "zz" * 32,
        b"31cfe6d670a19c81972252e3a1bc8b8338b36518d109de06ca27631f423ac845",
        None,
    ],
)
def test_malformed_keys_are_rejected(value: object) -> None:
    with pytest.raises(InvariantViolationError, match="dedupe key"):
        DedupeKey(value)  # type: ignore[arg-type]


@given(rule_version=st.uuids(), business=st.uuids(), channel=st.sampled_from(Channel))
def test_key_is_deterministic_and_equals_the_digest(
    rule_version: UUID, business: UUID, channel: Channel
) -> None:
    first = DedupeKey.for_notification(RuleVersionId(rule_version), BusinessId(business), channel)
    second = DedupeKey.for_notification(RuleVersionId(rule_version), BusinessId(business), channel)
    assert first == second
    assert first.value == _expected(RuleVersionId(rule_version), BusinessId(business), channel)
