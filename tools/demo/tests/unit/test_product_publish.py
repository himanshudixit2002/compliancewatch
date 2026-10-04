"""The demo publication of the local product, against the one deployable on memory stores.

The app runs as ``cw-mvp serve`` runs it, on two free local ports (``running_app``), with
publishing on and the rulebook's two shared tokens, as ``make product`` starts it. Every rule of
the seed calendar is loaded as a draft, as ``make seed SERVICE=rulebook`` loads them. ``cw-product
publish`` then registers the recorded notifications world.yaml uses through the pipeline's
client and takes the three GSTR-3B rules through citing, a high-impact submission, two synthetic
approvals by different reviewers and publishing; gstr9_annual follows when asked for. Every
published version still reads needs_review, the other seed rules stay drafts, no version reads
reviewed, a second run changes nothing, and the tool refuses to run outside local and test or in
token mode.
"""

from collections.abc import Iterator
from typing import Any, Final

import pytest

from cw_demo.product.analysts import DRAFTER, FIRST_REVIEWER, NOTE, SECOND_REVIEWER
from cw_demo.product.cli import main
from cw_demo.product.client import Product, ProductError, ProductSettings
from cw_demo.product.publish import DEFAULT_RULES, publish, rule_versions
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.ids import RuleVersionId, UserId
from domain_kernel.predicates import specification_to_mapping
from ontology import load as load_ontology
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.publication import DecisionAction
from rulebook.infrastructure.memory import MemoryKnowledgeStore

WRITE_TOKEN: Final = "product-test-write-token"
REVIEW_TOKEN: Final = "product-test-review-token"
CALENDAR: Final = load_calendar(load_ontology())
GSTR9: Final = "gstr9_annual"
SERVICES: Final = {
    **MEMORY_SERVICES,
    "rulebook": {
        "rulebook_store": "memory",
        "rulebook_publish_enabled": True,
        "rulebook_write_token": WRITE_TOKEN,
        "rulebook_review_token": REVIEW_TOKEN,
    },
}
"""The memory stores, and the rulebook as ``make product`` configures it."""


def store_of(app: CombinedApp) -> MemoryKnowledgeStore:
    store = app.services["rulebook"].state.wiring.unit_of_work
    assert isinstance(store, MemoryKnowledgeStore)
    return store


def load_seed_drafts(store: MemoryKnowledgeStore) -> None:
    """Every seed rule as a draft, as the seed command writes them to Postgres."""
    for seed in CALENDAR.rules:
        store.add_rule(
            seed.rule_key,
            title=seed.title,
            regulator=seed.regulator,
            level=seed.level,
            effective_from=seed.effective_from,
            summary=seed.summary,
            specification=specification_to_mapping(seed.specification),
            obligation_template=seed.obligation_template.to_mapping(),
            recurrence=None if seed.recurrence is None else seed.recurrence.to_mapping(),
        )


def settings_for(app: CombinedApp, **overrides: Any) -> ProductSettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "cw-product",
        "mvp_host": LOCALHOST,
        "mvp_public_port": app.settings.mvp_public_port,
        "mvp_internal_port": app.settings.mvp_internal_port,
        "mvp_internal_url": app.settings.mvp_internal_url,
        "rulebook_write_token": WRITE_TOKEN,
        "rulebook_review_token": REVIEW_TOKEN,
    }
    values.update(overrides)
    return ProductSettings(**values)


@pytest.fixture
def app() -> Iterator[CombinedApp]:
    with running_app(service_overrides=SERVICES) as running:
        load_seed_drafts(store_of(running))
        yield running


@pytest.fixture
def product(app: CombinedApp) -> Iterator[Product]:
    with Product.connect(settings_for(app)) as connected:
        yield connected


def by_status(product: Product) -> dict[str, list[str]]:
    """Every seed rule's versions as ``status/seed_status``, by rule key."""
    return {
        rule.rule_key: [
            f"{version['status']}/{version['seed_status']}"
            for version in rule_versions(product, rule.rule_key)
        ]
        for rule in CALENDAR.rules
    }


def test_the_three_gstr3b_rules_are_published_and_still_need_review(
    app: CombinedApp, product: Product
) -> None:
    publication = publish(product)

    assert [d.external_ref for d in publication.documents] == [
        "01/2026-Central Tax",
        "17/2025-Central Tax",
        "15/2025-Central Tax",
        "10/2025-Central Tax",
        "13/2024-Central Tax",
    ]
    assert all(document.created for document in publication.documents)
    assert [rule.rule_key for rule in publication.rules] == list(DEFAULT_RULES)
    for rule in publication.rules:
        assert (rule.status, rule.seed_status, rule.version) == ("published", "needs_review", 1)
        assert rule.citations >= 1
        assert rule.steps == (
            "cited",
            f"submitted by {DRAFTER.name}",
            f"approved by {FIRST_REVIEWER.name}",
            f"approved by {SECOND_REVIEWER.name}",
            f"published by {FIRST_REVIEWER.name}",
        )

    statuses = by_status(product)
    assert {key for key, seen in statuses.items() if seen == ["published/needs_review"]} == set(
        DEFAULT_RULES
    )
    drafts = {key for key, seen in statuses.items() if seen == ["draft/needs_review"]}
    assert drafts == {rule.rule_key for rule in CALENDAR.rules} - set(DEFAULT_RULES)
    assert len(drafts) == 10
    assert not any(s.split("/")[1] == "reviewed" for seen in statuses.values() for s in seen)

    store = store_of(app)
    monthly = RuleVersionId.parse(publication.rules[0].rule_version_id)
    decisions = store.decisions(monthly)
    assert [d.action for d in decisions] == [
        DecisionAction.SUBMITTED,
        DecisionAction.APPROVED,
        DecisionAction.APPROVED,
        DecisionAction.PUBLISHED,
    ]
    approvers = {d.actor_id for d in decisions if d.action is DecisionAction.APPROVED}
    assert approvers == {UserId(FIRST_REVIEWER.user_id), UserId(SECOND_REVIEWER.user_id)}
    assert {d.note for d in decisions} == {NOTE}
    with store() as uow:
        record = uow.rule_versions.get(monthly)
    assert record is not None
    assert record.high_impact


def test_a_second_run_changes_nothing_and_the_fourth_rule_follows_on_demand(
    product: Product,
) -> None:
    publish(product)
    again = publish(product)
    assert not any(document.created for document in again.documents)
    assert all(rule.steps == () for rule in again.rules), "already published"

    fourth = publish(product, [GSTR9])
    (rule,) = fourth.rules
    assert (rule.rule_key, rule.status, rule.seed_status) == (GSTR9, "published", "needs_review")
    statuses = by_status(product)
    published = {key for key, seen in statuses.items() if seen == ["published/needs_review"]}
    assert published == {*DEFAULT_RULES, GSTR9}
    assert sum(seen == ["draft/needs_review"] for seen in statuses.values()) == 9


def test_only_the_seed_rules_the_world_cites_can_be_published(product: Product) -> None:
    with pytest.raises(ProductError, match=r"only the seed rules world\.yaml cites"):
        publish(product, ["gstr1_monthly"])
    assert by_status(product)["gstr1_monthly"] == ["draft/needs_review"]


def test_a_rulebook_without_the_seed_calendar_is_reported() -> None:
    with (
        running_app(service_overrides=SERVICES) as empty,
        Product.connect(settings_for(empty)) as product,
        pytest.raises(ProductError, match="make seed SERVICE=rulebook"),
    ):
        publish(product)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"env": "staging"}, "CW_ENV is local or test, not staging"),
        ({"env": "prod", "auth_mode": "token"}, "CW_ENV is local or test, not prod"),
        ({"auth_mode": "token"}, "CW_AUTH_MODE header or dual, not token"),
    ],
)
def test_the_tool_refuses_outside_local_and_test_and_in_token_mode(
    app: CombinedApp,
    product: Product,
    overrides: dict[str, str],
    reason: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["publish"], settings=settings_for(app, **overrides)) == 2
    assert reason in capsys.readouterr().err
    assert all(seen == ["draft/needs_review"] for seen in by_status(product).values()), (
        "nothing was published"
    )
