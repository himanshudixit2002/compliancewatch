"""Rule versions: the ones in force on a date, every version of one rule, one version with its
citations. Open reads."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from domain_kernel.ids import RuleVersionId
from py_common.problems import problem_responses
from rulebook.api.deps import Wired
from rulebook.api.read_schemas import CitationOut, RuleVersionDetailOut, RuleVersionOut

router = APIRouter(tags=["rules"])

RULE_KEY = r"^[a-z][a-z0-9_]*$"


@router.get(
    "/rule-versions",
    summary="Rule versions in force on a date: published or superseded, as_of in their period",
)
def list_rule_versions(
    wired: Wired,
    as_of: date,
    rule_key: Annotated[str | None, Query(max_length=80)] = None,
    regulator: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    after: Annotated[
        str | None, Query(max_length=80, description="Continue after this rule key")
    ] = None,
) -> list[RuleVersionOut]:
    found = wired.list_rules_in_force.run(
        as_of, rule_key=rule_key, regulator=regulator, limit=limit, after=after
    )
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
    finds the version to cite, submit and publish. 404 when no rule has the key."""
    return [RuleVersionOut.from_record(record) for record in wired.list_rule_versions.run(rule_key)]


@router.get(
    "/rule-versions/{rule_version_id}",
    summary="One rule version in any status, with its citations",
    responses=problem_responses(404),
)
def read_rule_version(rule_version_id: UUID, wired: Wired) -> RuleVersionDetailOut:
    record, citations = wired.read_rule_version.run(RuleVersionId(rule_version_id))
    return RuleVersionDetailOut.from_detail(record, citations)


@router.get(
    "/rule-versions/{rule_version_id}/citations",
    summary="The clauses a rule version cites, with the quotes and their verification",
    responses=problem_responses(404),
)
def list_citations(rule_version_id: UUID, wired: Wired) -> list[CitationOut]:
    citations = wired.list_citations.run(RuleVersionId(rule_version_id))
    return [CitationOut.from_record(citation) for citation in citations]
