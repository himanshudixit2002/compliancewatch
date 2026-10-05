"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from obligation.application.changes import ApplyDeadlineChange, CloseObligation, WithdrawRule
from obligation.application.materialise import MaterialiseObligations
from obligation.application.queries import ListObligations
from obligation.application.tracking import (
    AddComment,
    AssignObligation,
    ChangeStatus,
    ReadObligation,
)
from obligation.domain.repository import UnitOfWorkFactory
from obligation.settings import ObligationSettings
from py_common.idempotency import IdempotencyStore


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: ObligationSettings
    unit_of_work: UnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    idempotency: IdempotencyStore
    materialise: MaterialiseObligations
    apply_deadline_change: ApplyDeadlineChange
    withdraw_rule: WithdrawRule
    close_obligation: CloseObligation
    list_obligations: ListObligations
    read_obligation: ReadObligation
    change_status: ChangeStatus
    assign: AssignObligation
    add_comment: AddComment
