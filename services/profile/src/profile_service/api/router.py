"""Routes of the profile service. Business logic lives in the application use cases."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import BusinessId, UserId
from profile_service.api.deps import Tenant, Wired
from profile_service.api.schemas import (
    FY_PATTERN,
    AttributesIn,
    EntityIn,
    LocationIn,
    NextQuestionOut,
    NodeOut,
    RegistrationIn,
    ReviewTaskOut,
    SetResultOut,
    SnapshotOut,
)
from profile_service.domain.errors import ProfileNodeNotFoundError
from profile_service.domain.events import ChangeSource
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/profile", tags=["profile"])


@router.get("/ping", summary="Router liveness")
async def ping() -> dict[str, str]:
    return {"service": "profile", "status": "pong"}


@router.post(
    "/entities",
    summary="Register a legal entity by PAN",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 422),
)
def create_entity(body: EntityIn, tenant: Tenant, wired: Wired) -> NodeOut:
    registered = wired.register.entity(tenant, Pan.parse(body.pan), body.name)
    return NodeOut.from_node(registered.node, created=registered.created)


@router.post(
    "/registrations",
    summary="Register a GSTIN; its PAN finds or creates the entity",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 422),
)
def create_registration(body: RegistrationIn, tenant: Tenant, wired: Wired) -> NodeOut:
    registered = wired.register.registration(
        tenant, Gstin.parse(body.gstin), body.name, entity_name=body.entity_name
    )
    return NodeOut.from_node(registered.node, created=registered.created)


@router.post(
    "/locations",
    summary="Register a place of business under a registration",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 404, 422),
)
def create_location(body: LocationIn, tenant: Tenant, wired: Wired) -> NodeOut:
    registered = wired.register.location(
        tenant, BusinessId(body.registration_id), body.label, body.name
    )
    return NodeOut.from_node(registered.node, created=registered.created)


@router.get(
    "/nodes/{node_id}",
    summary="One node with its stored attribute values",
    responses=problem_responses(401, 404),
)
def get_node(node_id: UUID, tenant: Tenant, wired: Wired) -> NodeOut:
    with wired.unit_of_work(tenant) as uow:
        node = uow.profiles.get(BusinessId(node_id))
    if node is None:
        raise ProfileNodeNotFoundError(str(node_id))
    return NodeOut.from_node(node)


@router.put(
    "/nodes/{node_id}/attributes",
    summary="Store attribute values, unsure answers and does-not-apply answers",
    responses=problem_responses(401, 404, 422),
)
def set_attributes(node_id: UUID, body: AttributesIn, tenant: Tenant, wired: Wired) -> SetResultOut:
    result = wired.set_attributes.run(
        tenant,
        BusinessId(node_id),
        [change.to_change() for change in body.changes],
        source=ChangeSource(body.source),
        by=None if body.changed_by is None else UserId(body.changed_by),
    )
    return SetResultOut(
        node=NodeOut.from_node(result.node),
        changed=list(result.changed),
        review_tasks=[task.value for task in result.review_tasks],
    )


@router.get(
    "/nodes/{node_id}/snapshot",
    summary="The attributes the engine evaluates: inherited down the lineage, for one year",
    responses=problem_responses(401, 404, 422),
)
def snapshot(
    node_id: UUID,
    tenant: Tenant,
    wired: Wired,
    fy: Annotated[
        str | None, Query(pattern=FY_PATTERN, description="2025-26; empty means no per-year values")
    ] = None,
) -> SnapshotOut:
    as_of_fy = None if fy is None else FinancialYear.parse(fy)
    return SnapshotOut.from_snapshot(
        wired.build_snapshot.run(tenant, BusinessId(node_id), as_of_fy=as_of_fy)
    )


@router.get(
    "/nodes/{node_id}/next-question",
    summary="One attribute to ask for next, or none when the level is complete",
    responses=problem_responses(401, 404, 422),
)
def next_question(
    node_id: UUID,
    tenant: Tenant,
    wired: Wired,
    fy: Annotated[str, Query(pattern=FY_PATTERN, description="2025-26")],
) -> NextQuestionOut:
    as_of_fy = FinancialYear.parse(fy)
    key = wired.next_question.run(tenant, BusinessId(node_id), as_of_fy=as_of_fy)
    definition = None if key is None else wired.ontology.require(key)
    return NextQuestionOut(
        node_id=node_id,
        as_of_fy=as_of_fy.label,
        attribute=key,
        definition=None if definition is None else definition.definition,
        type=None if definition is None else definition.type.value,
        allowed_values=[] if definition is None else list(definition.allowed_values),
    )


@router.get(
    "/nodes/{node_id}/review-tasks",
    summary="Open review tasks of a node",
    responses=problem_responses(401, 404),
)
def review_tasks(node_id: UUID, tenant: Tenant, wired: Wired) -> list[ReviewTaskOut]:
    with wired.unit_of_work(tenant) as uow:
        if uow.profiles.get(BusinessId(node_id)) is None:
            raise ProfileNodeNotFoundError(str(node_id))
        tasks = uow.profiles.open_review_tasks(BusinessId(node_id))
    return [ReviewTaskOut.from_task(task) for task in tasks]
