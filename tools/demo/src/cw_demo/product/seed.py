"""``cw-product seed``: the synthetic tenants, the demo publication and the first decisions.

The steps ``apps/web/scripts/seed`` takes for the web stack, through the services' HTTP APIs on
the internal listener, for each tenant of ``tenants.TENANTS``:

1. identity: the consents of the tenant's owner (or the CA firm's admin) for the onboarding's
   purposes, each with the notice version of its document in ``docs/legal``
   (``<document>@<Version line>``, as the web consent step records it). They come from the API,
   not from a person, and the evidence says so; a purpose already granted under that version is
   not recorded again;
2. profile: each business's GSTIN registration with its entity (found again by the GSTIN on a
   later run), the GSTIN pre-fill, and the answers on both nodes, the turnover for the financial
   year of today in India, which the engine evaluates by default;
3. notification: the tenant's recipient, with WhatsApp first and email second and the
   registrations it follows, and an opt-in for each address with no quiet hours of their own,
   so a change card reaches the sink at any hour (21:00 to 08:00 IST still holds every other
   address).

Then the business tenant is recorded in ``var/seed/last.json`` in the shape the web seed writes
(``seedState`` in ``apps/web/scripts/seed/report.mts``), so the web app's development sign-in
offers it even when a later step fails; the seed rules the golden world cites are published
(``publish``); and the engine decides them for every seeded registration (``evaluate``). Every
step can run again: it finds what the first run made and stores nothing twice.
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from cw_demo.product.client import GOLDEN, REPO, STATE_PATH, Product, ProductError, as_tenant, ok
from cw_demo.product.evaluate import Decision, evaluate, today_in_india
from cw_demo.product.publish import DEFAULT_RULES, Publication, publish
from cw_demo.product.tenants import (
    BUSINESS_TENANT,
    TENANTS,
    SyntheticBusiness,
    SyntheticTenant,
)
from cw_evals.qa.world import load_world
from domain_kernel.financial_year import FinancialYear

LEGAL: Final = REPO / "docs" / "legal"
PURPOSE_DOCUMENTS: Final = {
    "terms": "terms-of-service",
    "privacy_notice": "privacy-notice",
    "profile_processing": "privacy-notice",
    "whatsapp_reminders": "whatsapp-consent",
    "email_reminders": "privacy-notice",
}
"""The purposes the seed consents to and the document each refers to, as the web consent step
maps them (``PURPOSE_DOCUMENT`` in ``apps/web/src/features/consents/model/purposes.ts``)."""
CONSENT_SOURCE: Final = "api"
EVIDENCE: Final = "synthetic tenant from cw-product seed - no person gave this consent"
LANGUAGE: Final = "en"
ANY_HOUR: Final = "00:00"
"""Both ends of the quiet hours at one time: none, as a person may choose on the settings page."""
SEED_SERVICES: Final = (
    "identity",
    "profile",
    "rulebook",
    "applicability-engine",
    "obligation",
    "notification",
    "qa",
    "llm-gateway",
    "eval",
    "pipeline",
)
"""``SEED_SERVICES`` of ``apps/web/scripts/seed/lib.mts``: the keys of the state's services."""
VERSION_LINE: Final = re.compile(r"^Version:[ \t]*(\S+)[ \t]*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class BusinessSeed:
    key: str
    name: str
    gstin: str
    entity_id: str
    registration_id: str
    created: bool
    prefilled: tuple[str, ...]
    answered: int


@dataclass(frozen=True, slots=True)
class TenantSeed:
    key: str
    tenant_id: str
    kind: str
    name: str
    owner_id: str
    consents_recorded: tuple[str, ...]
    businesses: tuple[BusinessSeed, ...]
    recipient_id: str
    addresses: tuple[str, ...]


@dataclass
class SeedReport:
    seeded_at: str
    tenants: list[TenantSeed] = field(default_factory=list)
    state_path: str = ""
    publication: Publication | None = None
    decisions: list[Decision] = field(default_factory=list)


def notice_versions(legal: Path = LEGAL) -> dict[str, str]:
    """Each purpose's notice version, ``terms-of-service@0.1-draft``."""
    versions: dict[str, str] = {}
    for purpose, document in PURPOSE_DOCUMENTS.items():
        match = VERSION_LINE.search((legal / f"{document}.md").read_text(encoding="utf-8"))
        if match is None:
            raise ProductError(f"docs/legal/{document}.md has no Version line")
        versions[purpose] = f"{document}@{match.group(1)}"
    return versions


def seed_consents(
    product: Product, tenant: SyntheticTenant, versions: dict[str, str]
) -> tuple[str, ...]:
    headers = as_tenant(tenant.tenant_id)
    subject = str(tenant.owner_id)
    summary = ok(
        product.internal.get("/v1/identity/consents", params={"subject": subject}, headers=headers)
    )
    held = {
        (state["purpose"], state["notice_version"])
        for state in summary["states"]
        if state["granted"]
    }
    recorded: list[str] = []
    for purpose, version in versions.items():
        if (purpose, version) in held:
            continue
        body = {
            "subject": subject,
            "purpose": purpose,
            "source": CONSENT_SOURCE,
            "notice_version": version,
            "evidence": EVIDENCE,
            "recorded_by": subject,
            "granted": True,
        }
        ok(product.internal.post("/v1/identity/consents", json=body, headers=headers), 201)
        recorded.append(purpose)
    return tuple(recorded)


def seed_business(
    product: Product, tenant: SyntheticTenant, business: SyntheticBusiness, fy: FinancialYear
) -> BusinessSeed:
    headers = as_tenant(tenant.tenant_id)
    node = ok(
        product.internal.post(
            "/v1/profile/registrations",
            json={
                "gstin": business.gstin,
                "name": business.registration_name,
                "entity_name": business.name,
            },
            headers=headers,
        ),
        200,
        201,
    )
    registration_id, entity_id = str(node["id"]), str(node["parent_id"])
    prefill = ok(
        product.internal.post(
            f"/v1/profile/registrations/{registration_id}/prefill",
            json={"changed_by": str(tenant.owner_id)},
            headers=headers,
        )
    )
    answered = 0
    for node_id, answers in (
        (entity_id, business.entity_answers),
        (registration_id, business.registration_answers),
    ):
        changes: list[dict[str, Any]] = []
        for key, value in answers.items():
            change: dict[str, Any] = {"key": key, "value": value}
            if key in business.per_year:
                change["as_of_fy"] = fy.label
            changes.append(change)
        ok(
            product.internal.put(
                f"/v1/profile/nodes/{node_id}/attributes",
                json={
                    "changes": changes,
                    "source": "user_input",
                    "changed_by": str(tenant.owner_id),
                },
                headers=headers,
            )
        )
        answered += len(changes)
    return BusinessSeed(
        key=business.key,
        name=business.name,
        gstin=business.gstin,
        entity_id=entity_id,
        registration_id=registration_id,
        created=bool(node.get("created", False)),
        prefilled=tuple(prefill["applied"]),
        answered=answered,
    )


def seed_recipient(
    product: Product, tenant: SyntheticTenant, businesses: Sequence[BusinessSeed]
) -> tuple[str, ...]:
    """The tenant's recipient and the opt-in of each of its addresses."""
    headers = as_tenant(tenant.tenant_id)
    addresses = (("whatsapp", tenant.phone), ("email", tenant.email))
    body = {
        "user_id": str(tenant.owner_id),
        "role": tenant.role,
        "language": LANGUAGE,
        "digest_mode": "off",
        "org_label": tenant.name if tenant.kind == "ca_firm" else "",
        "addresses": [{"channel": channel, "address": address} for channel, address in addresses],
        "businesses": [
            {"business_id": business.registration_id, "label": business.name}
            for business in businesses
        ],
    }
    ok(
        product.internal.put(
            f"/v1/notification/recipients/{tenant.recipient_id}", json=body, headers=headers
        )
    )
    for channel, address in addresses:
        ok(
            product.internal.put(
                f"/v1/notification/preferences/{channel}/{address}",
                json={
                    "opted_in": True,
                    "source": CONSENT_SOURCE,
                    "language": LANGUAGE,
                    "quiet_hours_start": ANY_HOUR,
                    "quiet_hours_end": ANY_HOUR,
                },
            )
        )
    return tuple(address for _, address in addresses)


def seed_tenant(
    product: Product, tenant: SyntheticTenant, versions: dict[str, str], fy: FinancialYear
) -> TenantSeed:
    consents = seed_consents(product, tenant, versions)
    businesses = tuple(seed_business(product, tenant, b, fy) for b in tenant.businesses)
    addresses = seed_recipient(product, tenant, businesses)
    return TenantSeed(
        key=tenant.key,
        tenant_id=str(tenant.tenant_id),
        kind=tenant.kind,
        name=tenant.name,
        owner_id=str(tenant.owner_id),
        consents_recorded=consents,
        businesses=businesses,
        recipient_id=str(tenant.recipient_id),
        addresses=addresses,
    )


def iso_millis(moment: datetime) -> str:
    """``2026-10-04T09:30:00.000Z``, the form JavaScript's ``toISOString`` writes."""
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def seed_state(
    tenant: TenantSeed, document_id: str | None, seeded_at: str, service_url: str
) -> dict[str, Any]:
    """What ``seedState`` in ``apps/web/scripts/seed/report.mts`` records, key for key."""
    business = tenant.businesses[0]
    return {
        "tenant_id": tenant.tenant_id,
        "owner_id": tenant.owner_id,
        "entity_node_id": business.entity_id,
        "registration_node_id": business.registration_id,
        "document_id": document_id,
        "seeded_at": seeded_at,
        "services": dict.fromkeys(SEED_SERVICES, service_url),
    }


def write_state(path: Path, state: dict[str, Any]) -> Path:
    """``seedStateJson``: two-space JSON and a final newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path.resolve()


def seed(
    product: Product,
    *,
    rules: Sequence[str] = DEFAULT_RULES,
    golden: Path = GOLDEN,
    state_path: Path = STATE_PATH,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SeedReport:
    report = SeedReport(seeded_at=iso_millis(now()))
    fy = FinancialYear.for_date(today_in_india(now()))
    versions = notice_versions()
    report.tenants = [seed_tenant(product, tenant, versions, fy) for tenant in TENANTS]
    business = next(seeded for seeded in report.tenants if seeded.key == BUSINESS_TENANT.key)
    state = seed_state(business, first_notification(golden), report.seeded_at, product.internal_url)
    report.state_path = str(write_state(state_path, state))
    report.publication = publish(product, rules, golden=golden)
    report.decisions = evaluate(product, TENANTS, now=now)
    return report


def first_notification(golden: Path) -> str:
    """The id of the world's first recorded notification (01/2026-Central Tax), which the
    publication registers and the monthly rule cites: the state's ``document_id``."""
    world = load_world(golden)
    return str(world.cases[world.documents[0].key].document.document_id)
