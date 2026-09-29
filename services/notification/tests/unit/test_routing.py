import pytest

from domain_kernel.channels import Channel
from domain_kernel.ids import BusinessId, ObligationId, TenantId
from notification.domain.occasions import Occasion, OccasionKind
from notification.domain.routing import EVENT_ROUTES, TOPICS, ObligationNotice, Route, route
from notification.domain.templates import CHANGE_TEMPLATES, find_template


def test_the_routes_are_the_final_table() -> None:
    assert dict(EVENT_ROUTES) == {
        ("obligation.created", None): Route("change_card", OccasionKind.CHANGE_CARD),
        ("obligation.due_soon", None): Route("obligation_due_soon", OccasionKind.REMINDER),
        ("obligation.rescheduled", "deadline_extended"): Route(
            "obligation_deadline_extended", OccasionKind.RESCHEDULE
        ),
        ("obligation.rescheduled", "corrected"): Route(
            "obligation_corrected", OccasionKind.RESCHEDULE
        ),
        ("obligation.rescheduled", "manual"): None,
        ("obligation.closed", "rule_withdrawn"): Route(
            "obligation_withdrawn", OccasionKind.CLOSURE
        ),
        ("obligation.closed", "profile_changed"): Route("obligation_closed", OccasionKind.CLOSURE),
        ("obligation.closed", "rule_superseded"): Route("obligation_closed", OccasionKind.CLOSURE),
        ("obligation.closed", "completed"): None,
        ("obligation.closed", "waived_by_user"): None,
    }
    assert {topic for topic, _ in EVENT_ROUTES} == set(TOPICS)


def test_the_deadline_changes_use_the_change_log_templates() -> None:
    for (topic, reason), key in CHANGE_TEMPLATES.items():
        found = route(topic, reason)
        assert found is not None
        assert found.template_key == key


@pytest.mark.parametrize("found", [r for r in EVENT_ROUTES.values() if r is not None])
def test_every_route_has_whatsapp_in_two_languages_and_email(found: Route) -> None:
    for channel, language in ((Channel.WHATSAPP, "en"), (Channel.WHATSAPP, "hi")):
        assert find_template(found.template_key, channel, language).language == language
    assert find_template(found.template_key, Channel.EMAIL, "en").subject


def test_an_unknown_topic_or_reason_sends_nothing() -> None:
    assert route("obligation.created", "odd") is None
    assert route("obligation.closed") is None
    assert route("profile.updated") is None


def test_a_notice_carries_its_facts_read_only() -> None:
    notice = ObligationNotice(
        tenant_id=TenantId.new(),
        business_id=BusinessId.new(),
        occasion=Occasion.closure(ObligationId.new()),
        template_key="obligation_closed",
        params={"close_reason": "profile_changed"},
    )
    with pytest.raises(TypeError):
        notice.params["close_reason"] = "x"  # type: ignore[index]
