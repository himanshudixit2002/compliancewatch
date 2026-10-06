"""The local product's seed against the one deployable on memory stores, and the check steps that
need no worker.

The app runs as ``make product`` configures it (publishing on, the rulebook's tokens, the
profile's static GSTIN lookup), with the seed calendar loaded as drafts. ``cw-product seed``
creates the business tenant and the CA firm with its two clients through the services' APIs,
publishes the three GSTR-3B rules and has the engine decide them for every registration: each
decision is the one the synthetic answers call for. It records the business tenant for the web
app's development sign-in in the shape the web seed writes, and a second run finds everything the
first one made. The honesty and isolation steps of ``cw-product check`` pass on the result; the
loop and health steps need the worker, which ``make product-check`` proves on the dev stack.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import SecretStr

from cw_demo.product.check import CheckContext, run_checks, select
from cw_demo.product.cli import main
from cw_demo.product.client import Product, ProductSettings
from cw_demo.product.publish import DEFAULT_RULES
from cw_demo.product.seed import PURPOSE_DOCUMENTS, SEED_SERVICES, seed
from cw_demo.product.tenants import BUSINESS_TENANT, CA_FIRM_TENANT, TENANTS
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.predicates import specification_to_mapping
from ontology import load as load_ontology
from rulebook.application.seed_loader import load_calendar
from rulebook.infrastructure.memory import MemoryKnowledgeStore

REPO: Final = Path(__file__).resolve().parents[4]
WEB_SEED_LIB: Final = REPO / "apps" / "web" / "scripts" / "seed" / "lib.mts"
WRITE_TOKEN: Final = "product-test-write-token"
REVIEW_TOKEN: Final = "product-test-review-token"
SERVICES: Final = {
    **MEMORY_SERVICES,
    "profile": {"profile_store": "memory", "profile_gstin_lookup": "static"},
    "rulebook": {
        "rulebook_store": "memory",
        "rulebook_publish_enabled": True,
        "rulebook_write_token": WRITE_TOKEN,
        "rulebook_review_token": REVIEW_TOKEN,
    },
}
ISO_MILLIS: Final = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


@pytest.fixture
def app() -> Iterator[CombinedApp]:
    with running_app(service_overrides=SERVICES) as running:
        store = running.services["rulebook"].state.wiring.unit_of_work
        assert isinstance(store, MemoryKnowledgeStore)
        for rule in load_calendar(load_ontology()).rules:
            store.add_rule(
                rule.rule_key,
                title=rule.title,
                regulator=rule.regulator,
                level=rule.level,
                effective_from=rule.effective_from,
                specification=specification_to_mapping(rule.specification),
                obligation_template=rule.obligation_template.to_mapping(),
                recurrence=None if rule.recurrence is None else rule.recurrence.to_mapping(),
            )
        yield running


def settings_for(app: CombinedApp) -> ProductSettings:
    return ProductSettings(
        _env_file=None,
        service_name="cw-product",
        mvp_host=LOCALHOST,
        mvp_public_port=app.settings.mvp_public_port,
        mvp_internal_port=app.settings.mvp_internal_port,
        mvp_internal_url=app.settings.mvp_internal_url,
        rulebook_write_token=SecretStr(WRITE_TOKEN),
        rulebook_review_token=SecretStr(REVIEW_TOKEN),
    )


@pytest.fixture
def product(app: CombinedApp) -> Iterator[Product]:
    with Product.connect(settings_for(app)) as connected:
        yield connected


def web_seed_state_keys() -> list[str]:
    """The fields of ``SeedState`` in the web seed, in their order."""
    text = WEB_SEED_LIB.read_text(encoding="utf-8")
    block = re.search(r"export interface SeedState \{(.*?)\n\}", text, re.DOTALL)
    assert block is not None
    return re.findall(r"^\s+(\w+):", block.group(1), re.MULTILINE)


def web_seed_services() -> list[str]:
    text = WEB_SEED_LIB.read_text(encoding="utf-8")
    block = re.search(r"export const SEED_SERVICES = \[(.*?)\]", text, re.DOTALL)
    assert block is not None
    return re.findall(r'"([a-z-]+)"', block.group(1))


def test_the_seed_makes_both_tenants_publishes_and_decides(
    product: Product, tmp_path: Path
) -> None:
    state_path = tmp_path / "seed" / "last.json"
    report = seed(product, state_path=state_path)

    business, firm = report.tenants
    assert (business.name, firm.name) == (BUSINESS_TENANT.name, CA_FIRM_TENANT.name)
    assert [b.key for b in firm.businesses] == ["client_karnataka", "client_delhi"]
    assert all(b.created for t in report.tenants for b in t.businesses)
    assert set(business.consents_recorded) == set(PURPOSE_DOCUMENTS)
    assert "registration_type" in business.businesses[0].prefilled, "the demo GSTIN pre-fills"
    assert report.publication is not None
    assert [rule.rule_key for rule in report.publication.rules] == list(DEFAULT_RULES)

    expected = {
        (tenant.key, b.key, rule): result
        for tenant in TENANTS
        for b in tenant.businesses
        for rule, result in b.expected.items()
        if rule in DEFAULT_RULES
    }
    decided = {(d.tenant, d.business, d.rule_key): d.result for d in report.decisions}
    assert decided == expected
    assert not any(d.replayed or d.needs_review for d in report.decisions)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert list(state) == web_seed_state_keys()
    assert list(state["services"]) == web_seed_services() == list(SEED_SERVICES)
    assert set(state["services"].values()) == {product.internal_url}
    assert state["tenant_id"] == str(BUSINESS_TENANT.tenant_id)
    assert state["owner_id"] == str(BUSINESS_TENANT.owner_id)
    assert state["registration_node_id"] == business.businesses[0].registration_id
    assert state["entity_node_id"] == business.businesses[0].entity_id
    assert state["document_id"] == report.publication.documents[0].document_id
    assert ISO_MILLIS.match(state["seeded_at"])
    assert state_path.read_text(encoding="utf-8").endswith("}\n")

    recipients = product.internal.get(
        "/v1/notification/recipients",
        params={"business_id": business.businesses[0].registration_id},
        headers={"x-tenant-id": business.tenant_id},
    ).json()["items"]
    (recipient,) = recipients
    assert [a["channel"] for a in recipient["addresses"]] == ["whatsapp", "email"]
    assert recipient["role"] == "owner"


def test_a_second_seed_finds_what_the_first_made(product: Product, tmp_path: Path) -> None:
    first = seed(product, state_path=tmp_path / "last.json")
    again = seed(product, state_path=tmp_path / "last.json")
    assert [t.consents_recorded for t in again.tenants] == [(), ()]
    assert not any(b.created for t in again.tenants for b in t.businesses)
    assert [b.registration_id for t in again.tenants for b in t.businesses] == [
        b.registration_id for t in first.tenants for b in t.businesses
    ]
    assert again.publication is not None
    assert all(rule.steps == () for rule in again.publication.rules)
    assert all(d.replayed for d in again.decisions), "the same day's decisions come back"
    assert [d.decision_id for d in again.decisions] == [d.decision_id for d in first.decisions]


def test_honesty_and_isolation_hold_after_the_seed(product: Product, tmp_path: Path) -> None:
    seed(product, state_path=tmp_path / "last.json")
    results = run_checks(CheckContext(product, timeout=5), select(["honesty", "isolation"]))
    assert [(r.name, r.ok, r.error) for r in results] == [
        ("honesty", True, ""),
        ("isolation", True, ""),
    ]
    honesty, isolation = results
    assert any("gstr3b_monthly v1" in line for line in honesty.details)
    assert any(CA_FIRM_TENANT.name in line for line in isolation.details)


def test_the_review_step_opens_claims_and_reads_seed_tasks_and_changes_no_rule(
    product: Product, tmp_path: Path
) -> None:
    seed(product, state_path=tmp_path / "last.json")
    context = CheckContext(product, timeout=5)
    (review,) = select(["review"])
    (honesty,) = select(["honesty"])
    first, kept, second = run_checks(context, [review, honesty, review])
    assert (first.name, first.ok, first.error) == ("review", True, "")
    drafts = 13 - len(DEFAULT_RULES)
    assert first.details[0] == f"seed tasks: {drafts} opened now, a second request opened none"
    assert "(claimed now)" in first.details[2]
    assert (kept.ok, kept.error) == (True, ""), "a claim changes no seed rule"
    assert (second.ok, second.error) == (True, "")
    assert second.details[0] == "seed tasks: 0 opened now, a second request opened none"
    assert "(held from an earlier run)" in second.details[2]


def test_isolation_fails_before_anything_is_seeded(product: Product) -> None:
    (result,) = run_checks(CheckContext(product, timeout=0.2, interval=0.05), select(["isolation"]))
    assert not result.ok
    assert "run cw-product seed" in result.error


def test_the_command_line_seeds_and_reports_json(
    app: CombinedApp, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "last.json"
    assert main(["seed", "--state", str(state), "--json"], settings=settings_for(app)) == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert report["state_path"] == str(state.resolve())
    assert len(report["decisions"]) == 9
    assert main(["evaluate", "--tenant", "business"], settings=settings_for(app)) == 0
    assert "made earlier today" in capsys.readouterr().out
    assert main(["publish", "--rule", "gstr9_annual"], settings=settings_for(app)) == 0
    assert "gstr9_annual" in capsys.readouterr().out
