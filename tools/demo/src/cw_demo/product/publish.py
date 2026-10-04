"""``cw-product publish``: publish the seed rules the golden world cites, as synthetic analysts.

``make seed SERVICE=rulebook`` writes the thirteen rules of
``services/rulebook/seed/gst_calendar.yaml`` as drafts. Four of them rest on a clause the
repository holds as recorded text: ``evals/golden/qa/kag/world.yaml`` cites gstr3b_monthly, both
quarterly GSTR-3B groups and gstr9_annual from recorded quotes (``supported``). Only those can be
published here, and the other nine stay drafts. ``DEFAULT_RULES`` are the three GSTR-3B rules;
gstr9_annual is published when asked for (``--rule gstr9_annual``).

1. The recorded CBIC notifications the world uses are registered through the rulebook's pipeline
   write route, with the pipeline's own client (``HttpRulebook``) and the write token: each one's
   clauses as its golden extraction case recorded them, under the source listing's title and
   date. Registering is idempotent, and a notification registered before with the same clauses
   (``make web-seed`` registers 01/2026) answers with the stored one.
2. Each rule's latest version (``GET /v1/rulebook/rules/{rule_key}/versions``) is cited with the
   world's quotes, which the rulebook verifies against the stored clause, submitted by
   ``analysts.DRAFTER`` tagged high impact, approved by both synthetic reviewers with
   ``synthetic: true`` and published, every step noted ``analysts.NOTE``. A version past draft
   picks up where an earlier run stopped; a published one is left as it is.
3. Each version is read back: published, with verified citations, and still needs_review, the
   seed calendar's review status, since no analyst has reviewed it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from cw_demo.product.analysts import DRAFTER, FIRST_REVIEWER, NOTE, REVIEWERS
from cw_demo.product.client import GOLDEN, Product, ProductError, ok, problem_slug
from cw_evals.qa.world import (
    MEDIA_TYPE,
    REGULATOR,
    SOURCE_ID,
    DocumentSpec,
    RuleSpec,
    WorldSpec,
    load_world,
)
from domain_kernel.ids import SourceId
from pipeline.domain.errors import (
    RulebookConflictError,
    RulebookRejectedError,
    RulebookUnavailableError,
)
from pipeline.domain.knowledge import DocumentRecord
from pipeline.infrastructure.parsers.pdf import PARSER_VERSION
from pipeline.infrastructure.rulebook_client import HttpRulebook

RULEBOOK: Final = "/v1/rulebook"
DEFAULT_RULES: Final = ("gstr3b_monthly", "gstr3b_quarterly_group_a", "gstr3b_quarterly_group_b")
NEEDS_REVIEW: Final = "needs_review"
DUPLICATE_APPROVER: Final = "rulebook-duplicate-approver"
FETCHED_AT: Final = datetime(2026, 9, 28, tzinfo=UTC)
"""When a case records no fetch time: the fixed date the recorded fixtures use."""

ClauseIds = Mapping[tuple[str, str], UUID]
"""The stored clause id of each (world document key, clause ref)."""


@dataclass(frozen=True, slots=True)
class RegisteredNotification:
    key: str
    external_ref: str
    document_id: str
    created: bool


@dataclass(frozen=True, slots=True)
class PublishedRule:
    rule_key: str
    rule_version_id: str
    version: int
    status: str
    seed_status: str
    citations: int
    steps: tuple[str, ...]
    """What this run did to the version; empty when it was published already."""


@dataclass(frozen=True, slots=True)
class Publication:
    documents: tuple[RegisteredNotification, ...]
    rules: tuple[PublishedRule, ...]


def supported(world: WorldSpec) -> tuple[str, ...]:
    """The seed rules the world cites from a recorded quote, in the world's order."""
    return tuple(rule.rule_key for rule in world.rules if rule.seed)


def publish(
    product: Product, rules: Sequence[str] = DEFAULT_RULES, *, golden: Path = GOLDEN
) -> Publication:
    world = load_world(golden)
    allowed = supported(world)
    unknown = [key for key in rules if key not in allowed]
    if unknown:
        raise ProductError(
            f"{', '.join(unknown)}: only the seed rules world.yaml cites from a recorded quote "
            f"can be published here ({', '.join(allowed)})"
        )
    documents, clause_ids = register_notifications(product, world)
    published = tuple(
        publish_rule(product, world.rule(key), clause_ids) for key in dict.fromkeys(rules)
    )
    return Publication(documents, published)


def notification_record(world: WorldSpec, spec: DocumentSpec) -> DocumentRecord:
    """A recorded notification as the pipeline registers it: the clauses of its extraction case
    under the source listing's title and publication date."""
    case = world.cases[spec.key]
    source = case.source
    document = replace(
        case.document,
        title=str(source.get("title") or case.document.title),
        published_at=spec.published_on,
        parser_version=PARSER_VERSION,
    )
    fetched = source.get("fetched_at")
    return DocumentRecord(
        document=document,
        source_id=SourceId(SOURCE_ID),
        sha256=str(source["sha256"]),
        regulator=REGULATOR,
        url=str(source["url"]),
        media_type=MEDIA_TYPE,
        fetched_at=FETCHED_AT if fetched is None else datetime.fromisoformat(str(fetched)),
        external_ref=spec.own_ref,
    )


def register_notifications(
    product: Product, world: WorldSpec
) -> tuple[tuple[RegisteredNotification, ...], ClauseIds]:
    writer = HttpRulebook(token=product.write_token(), client=product.internal)
    registered: list[RegisteredNotification] = []
    clause_ids: dict[tuple[str, str], UUID] = {}
    for spec in world.documents:
        try:
            answer = writer.register_document(notification_record(world, spec))
        except (RulebookConflictError, RulebookRejectedError, RulebookUnavailableError) as exc:
            raise ProductError(f"registering {spec.own_ref}: {exc}") from exc
        registered.append(
            RegisteredNotification(
                spec.key, spec.own_ref, str(answer.document_id), created=answer.created
            )
        )
        for ref, clause_id in answer.clause_ids.items():
            clause_ids[spec.key, ref] = clause_id.value
    return tuple(registered), clause_ids


def rule_versions(product: Product, rule_key: str) -> list[dict[str, Any]]:
    """Every version of the rule, by number; refuses a rule the seed command has not loaded."""
    answer = product.internal.get(f"{RULEBOOK}/rules/{rule_key}/versions")
    if answer.status_code == 404:
        raise ProductError(
            f"{rule_key} is not in the rulebook: load the seed calendar first "
            "(make seed SERVICE=rulebook)"
        )
    versions: list[dict[str, Any]] = ok(answer)
    return versions


def publish_rule(product: Product, rule: RuleSpec, clause_ids: ClauseIds) -> PublishedRule:
    versions = rule_versions(product, rule.rule_key)
    if not versions:
        raise ProductError(f"{rule.rule_key} has no version: run make seed SERVICE=rulebook")
    latest = versions[-1]
    version_id, status = str(latest["rule_version_id"]), str(latest["status"])
    path = f"{RULEBOOK}/rule-versions/{version_id}"
    headers = product.review_headers()
    steps: list[str] = []
    if status == "draft":
        citations = [
            {"clause_id": str(clause_ids[c.document, c.clause_ref]), "quote": c.quote}
            for c in rule.citations
        ]
        ok(
            product.internal.put(
                f"{path}/citations", json={"citations": citations}, headers=headers
            )
        )
        submit = {"actor_id": str(DRAFTER.user_id), "high_impact": True, "note": NOTE}
        status = ok(product.internal.post(f"{path}/submit", json=submit, headers=headers))["status"]
        steps += ["cited", f"submitted by {DRAFTER.name}"]
    for reviewer in REVIEWERS:
        if status != "in_review":
            break
        body = {"actor_id": str(reviewer.user_id), "note": NOTE, "synthetic": True}
        answer = product.internal.post(f"{path}/approve", json=body, headers=headers)
        if answer.status_code == 409 and problem_slug(answer) == DUPLICATE_APPROVER:
            continue  # an earlier run approved as this reviewer in the round
        status = ok(answer)["status"]
        steps.append(f"approved by {reviewer.name}")
    if status == "approved":
        body = {"actor_id": str(FIRST_REVIEWER.user_id), "note": NOTE}
        status = ok(product.internal.post(f"{path}/publish", json=body, headers=headers))["status"]
        steps.append(f"published by {FIRST_REVIEWER.name}")
    if status != "published":
        raise ProductError(
            f"{rule.rule_key} version {latest['version']} is {status}, not published: "
            "return it to draft in the rulebook, or publish it by hand"
        )
    return verified(product, rule.rule_key, version_id, tuple(steps))


def verified(
    product: Product, rule_key: str, version_id: str, steps: tuple[str, ...]
) -> PublishedRule:
    """The version as the rulebook now has it, refused unless it is published, cited and still
    needs_review."""
    detail = ok(product.internal.get(f"{RULEBOOK}/rule-versions/{version_id}"))
    citations = detail["citations"]
    if not citations or not all(citation["verified"] for citation in citations):
        raise ProductError(f"{rule_key} is published without verified citations")
    if detail["seed_status"] != NEEDS_REVIEW:
        raise ProductError(
            f"{rule_key} reads {detail['seed_status']}: a synthetic publication must leave the "
            "seed calendar's needs_review in place"
        )
    return PublishedRule(
        rule_key=rule_key,
        rule_version_id=version_id,
        version=int(detail["version"]),
        status=str(detail["status"]),
        seed_status=str(detail["seed_status"]),
        citations=len(citations),
        steps=steps,
    )
