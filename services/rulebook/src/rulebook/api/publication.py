"""Citations, review and publication of rule versions, and the daily transition sweep. Every
route writes, so every route needs the write token; publishing, withdrawing and the sweep also
need ``CW_RULEBOOK_PUBLISH_ENABLED``."""

from uuid import UUID

from fastapi import APIRouter

from domain_kernel.ids import RuleVersionId, UserId
from py_common.problems import problem_responses
from rulebook.api.deps import Wired, WriteAccess
from rulebook.api.publication_schemas import (
    ActorIn,
    CitationsIn,
    CitationsOut,
    LifecycleOut,
    PublicationOut,
    SubmitIn,
    TransitionsIn,
    TransitionsOut,
)

router = APIRouter(tags=["publication"], dependencies=[WriteAccess])


@router.put(
    "/rule-versions/{rule_version_id}/citations",
    summary="Cite clauses for a draft version; every quote must be in its clause",
    responses=problem_responses(401, 404, 409, 422, 503),
)
def add_citations(rule_version_id: UUID, body: CitationsIn, wired: Wired) -> CitationsOut:
    report = wired.add_citations.run(
        RuleVersionId(rule_version_id), [citation.to_input() for citation in body.citations]
    )
    return CitationsOut.from_report(report)


@router.post(
    "/rule-versions/{rule_version_id}/submit",
    summary="Submit a draft for review; starts a new approval round",
    responses=problem_responses(401, 404, 409, 503),
)
def submit(rule_version_id: UUID, body: SubmitIn, wired: Wired) -> LifecycleOut:
    state = wired.submit_version.run(
        RuleVersionId(rule_version_id),
        actor_id=UserId(body.actor_id),
        high_impact=body.high_impact,
        note=body.note,
    )
    return LifecycleOut.from_state(state)


@router.post(
    "/rule-versions/{rule_version_id}/return",
    summary="Send a version under review or approved back to draft; starts a new round",
    responses=problem_responses(401, 404, 409, 503),
)
def return_to_draft(rule_version_id: UUID, body: ActorIn, wired: Wired) -> LifecycleOut:
    state = wired.return_version.run(
        RuleVersionId(rule_version_id), actor_id=UserId(body.actor_id), note=body.note
    )
    return LifecycleOut.from_state(state)


@router.post(
    "/rule-versions/{rule_version_id}/approve",
    summary="Approve a version under review; high-impact versions need two different approvers",
    responses=problem_responses(401, 404, 409, 422, 503),
)
def approve(rule_version_id: UUID, body: ActorIn, wired: Wired) -> LifecycleOut:
    state = wired.approve_version.run(
        RuleVersionId(rule_version_id), actor_id=UserId(body.actor_id), note=body.note
    )
    return LifecycleOut.from_state(state)


@router.post(
    "/rule-versions/{rule_version_id}/publish",
    summary="Publish an approved version, apply its relations and write the rule events",
    responses=problem_responses(401, 404, 409, 422, 503),
)
def publish(rule_version_id: UUID, body: ActorIn, wired: Wired) -> PublicationOut:
    publication = wired.publish_version.run(
        RuleVersionId(rule_version_id), actor_id=UserId(body.actor_id), note=body.note
    )
    return PublicationOut.from_publication(publication)


@router.post(
    "/rule-versions/{rule_version_id}/withdraw",
    summary="Withdraw a published version with rule.withdrawn, effective today",
    responses=problem_responses(401, 404, 409, 503),
)
def withdraw(rule_version_id: UUID, body: ActorIn, wired: Wired) -> LifecycleOut:
    state = wired.withdraw_version.run(
        RuleVersionId(rule_version_id), actor_id=UserId(body.actor_id), note=body.note
    )
    return LifecycleOut.from_state(state)


@router.post(
    "/maintenance/transitions",
    summary="Move replaced versions whose replacement has taken effect (the daily sweep)",
    responses=problem_responses(401, 422, 503),
)
def apply_transitions(body: TransitionsIn, wired: Wired) -> TransitionsOut:
    return TransitionsOut.from_report(wired.apply_transitions.run(body.as_of))
