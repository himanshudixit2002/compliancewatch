"""Rule versions: the ones in force on a date or that ended on or after one, every version of one
rule, one version with its citations and approvers. Open reads."""

from datetime import date
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import RuleVersionId
from domain_kernel.status import RuleVersionStatus
from py_common.problems import problem_responses
from rulebook.api.deps import Wired
from rulebook.api.read_schemas import CitationOut, RuleVersionDetailOut, RuleVersionOut

router = APIRouter(tags=["rules"])

RULE_KEY = r"^[a-z][a-z0-9_]*$"


class ListedStatus(StrEnum):
    """The statuses a listing of versions holds: those of a version that has been published and
    was not withdrawn."""

    PUBLISHED = "published"
    SUPERSEDED = "superseded"


@router.get(
    "/rule-versions",
    summary=(
        "Rule versions in force on a date, or that ended on or after one: published or "
        "superseded, never withdrawn"
    ),
    responses=problem_responses(422),
)
def list_rule_versions(
    wired: Wired,
    as_of: Annotated[
        date | None,
        Query(description="The versions in force on this day: as_of in their effective period"),
    ] = None,
    ended_on_or_after: Annotated[
        date | None,
        Query(
            description=(
                "Instead of as_of, the versions whose effective_to (exclusive) is on or after this "
                "day: the ones superseded since then, whose periods may still be due, and the "
                "published ones a replacement has cut to end then or later; never a withdrawn one"
            )
        ),
    ] = None,
    status: Annotated[
        ListedStatus | None, Query(description="Only the versions of this status")
    ] = None,
    rule_key: Annotated[str | None, Query(max_length=80)] = None,
    regulator: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    after: Annotated[
        str | None, Query(max_length=80, description="Continue after this rule key")
    ] = None,
    after_version: Annotated[
        int | None,
        Query(
            ge=1,
            description=(
                "With after: continue after this version of that rule key, since a listing of "
                "ended versions can hold several versions of a rule"
            ),
        ),
    ] = None,
) -> list[RuleVersionOut]:
    """Name exactly one of ``as_of`` and ``ended_on_or_after`` (422 otherwise). Both listings are
    ordered by rule key, then version, and paged with ``limit``, ``after`` and
    ``after_version``."""
    wanted = None if status is None else RuleVersionStatus(status.value)
    if as_of is not None and ended_on_or_after is None:
        found = wired.list_rules_in_force.run(
            as_of,
            rule_key=rule_key,
            regulator=regulator,
            limit=limit,
            after=after,
            status=wanted,
            after_version=after_version,
        )
    elif ended_on_or_after is not None and as_of is None:
        found = wired.list_ended_versions.run(
            ended_on_or_after,
            rule_key=rule_key,
            regulator=regulator,
            limit=limit,
            after=after,
            status=wanted,
            after_version=after_version,
        )
    else:
        raise InvariantViolationError("name exactly one of as_of and ended_on_or_after")
    return [RuleVersionOut.from_record(record) for record in found]


@router.get(
    "/rules/{rule_key}/versions",
    summary="Every version of a rule in any status, by version number",
    responses=problem_responses(404, 422),
)
def list_versions_of_rule(
    wired: Wired,
    rule_key: Annotated[str, Path(max_length=80, pattern=RULE_KEY)],
) -> list[RuleVersionOut]:
    """The drafts the seed command writes as well as the versions past them: where a workbench
    finds the version to cite, submit and publish. A closed draft (its rule candidate was
    rejected) is listed with ``closed`` true: it never moves on, so a reader after the rule's
    latest version skips it. 404 when no rule has the key."""
    return [
        RuleVersionOut.from_record(listed.record, closed=listed.closed)
        for listed in wired.list_rule_versions.run(rule_key)
    ]


@router.get(
    "/rule-versions/{rule_version_id}",
    summary="One rule version in any status, with its citations and, once published, approvers",
    responses=problem_responses(404),
)
def read_rule_version(rule_version_id: UUID, wired: Wired) -> RuleVersionDetailOut:
    """``approved_by`` lists the approvers of the round the version was published from (two for
    a high-impact one) and ``published_at`` when it was published, so a reader that shows who
    reviewed a duty does not depend on having seen rule.published."""
    detail = wired.read_rule_version.run(RuleVersionId(rule_version_id))
    return RuleVersionDetailOut.from_detail(detail)


@router.get(
    "/rule-versions/{rule_version_id}/citations",
    summary="The clauses a rule version cites, with the quotes and their verification",
    responses=problem_responses(404),
)
def list_citations(rule_version_id: UUID, wired: Wired) -> list[CitationOut]:
    citations = wired.list_citations.run(RuleVersionId(rule_version_id))
    return [CitationOut.from_record(citation) for citation in citations]
