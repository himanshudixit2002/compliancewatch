"""A CA firm's bulk notification: ``POST /v1/notification/bulk``, part of the public API (tag
``public``, ``x-roles`` ca_admin and ca_staff).

The firm names a change and its affected clients, and each client's own people get the change
card once (``application.bulk``). The request takes an ``Idempotency-Key``: a retry with the same
key and body gets the first answer back for 24 hours, and a new key for the same change and
clients finds the cards queued already and answers them as duplicates. While the flag
``notification.bulk`` is off the route answers 503 before it looks at the key.
"""

from typing import Final

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from domain_kernel.ids import BusinessId, RuleVersionId
from notification.api.deps import PUBLIC_CA_ROUTE, Bulk, Wired
from notification.api.schemas import BulkNotificationIn, BulkNotificationOut
from notification.application.bulk import BulkRequest
from py_common.idempotency.fastapi import IDEMPOTENCY_RESPONSES, IdempotencyKey, run_idempotent
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/notification", tags=["public", "notifications"])

BULK_PROBLEMS: Final = {**problem_responses(401, 403, 422, 503), **IDEMPOTENCY_RESPONSES}


@router.post(
    "/bulk",
    summary="Send a change card to a CA firm's affected clients, once per change and person",
    status_code=status.HTTP_201_CREATED,
    response_model=BulkNotificationOut,
    responses=BULK_PROBLEMS,
    openapi_extra=PUBLIC_CA_ROUTE,
)
def bulk_notify(
    body: BulkNotificationIn, caller: Bulk, key: IdempotencyKey, wired: Wired
) -> JSONResponse:
    """Each business named gets the change card for the client's own people who follow it (an
    owner or staff, not the firm's own people, who hear in their daily digest), about its first
    open obligation of the change, through the same queue, quiet hours and batching as every
    card. A person who has the card of this change for the business already, from the change
    itself or an earlier request, gets nothing more (``skipped_duplicate``). A business nobody can
    be told about is ``skipped_no_recipient``, and one the change asks nothing of (no open
    obligation of it; another tenant's business reads the same) ``skipped_not_affected``. The
    audit entry ``notification.bulk`` names the caller and the counts. 503 while the flag
    ``notification.bulk`` is off or when the obligation service cannot answer."""
    wired.bulk.require_enabled()

    def produce() -> BulkNotificationOut:
        result = wired.bulk.run(
            BulkRequest(
                tenant_id=caller.tenant_id,
                rule_version_id=RuleVersionId(body.rule_version_id),
                business_ids=tuple(BusinessId(business) for business in body.business_ids),
                actor=caller.actor,
                kind=body.kind,
                correlation_id=caller.correlation_id,
            )
        )
        return BulkNotificationOut.from_result(result)

    return run_idempotent(
        wired.idempotency, caller.tenant_id, key, status.HTTP_201_CREATED, produce
    )
