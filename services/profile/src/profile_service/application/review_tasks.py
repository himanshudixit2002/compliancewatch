"""Close a review task by hand: ``POST /nodes/{node_id}/review-tasks/{task_id}/resolve``.

A task closes on its own when the attribute it asks about is answered
(``application.attributes.close_answered``). ``ResolveReviewTask`` is the other way: a tenant
admin or an analyst closes one with an outcome, ``confirmed`` (what the task asked about was
checked and stands) or ``dismissed`` (nothing to check, or checked elsewhere), and a note. The
task, its closure and the ``review_task.closed`` entry commit together. A task closed already is
refused (``ReviewTaskClosedError``, 409), and so is a task of another node or tenant
(``ReviewTaskNotFoundError``, 404).
"""

from collections.abc import Callable
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, TenantId
from profile_service.application.audit import record_review_task_closed
from profile_service.domain.errors import ProfileNodeNotFoundError, ReviewTaskNotFoundError
from profile_service.domain.model import ReviewOutcome, ReviewTask
from profile_service.domain.repository import UnitOfWorkFactory


class ResolveReviewTask:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        node_id: BusinessId,
        task_id: BusinessId,
        *,
        outcome: ReviewOutcome,
        note: str = "",
    ) -> ReviewTask:
        """The task, closed with ``outcome`` and ``note``."""
        now = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            if uow.profiles.get(node_id) is None:
                raise ProfileNodeNotFoundError(str(node_id))
            task = uow.profiles.get_review_task(task_id)
            if task is None or task.node_id != node_id:
                raise ReviewTaskNotFoundError(str(task_id))
            resolved = task.resolved(outcome, note, now)
            uow.profiles.save_review_task(resolved)
            record_review_task_closed(uow, resolved)
        return resolved
