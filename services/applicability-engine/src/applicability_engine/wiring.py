"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from applicability_engine.application.dry_run import DryRun
from applicability_engine.application.evaluate import EvaluateRule
from applicability_engine.application.export import ExportTenantData
from applicability_engine.application.fanout import (
    CancelFanOut,
    ListFanOuts,
    PauseFanOut,
    ReadFanOut,
    ReadHold,
    ReleaseHold,
    ResumeFanOut,
    SetHold,
)
from applicability_engine.application.impact import ReadChangeImpact
from applicability_engine.application.queries import ListDecisions, ReadDecision
from applicability_engine.application.review import ListReviewItems, ResolveReviewItem
from applicability_engine.domain.ports import ProfileReader, RulebookReader
from applicability_engine.domain.repository import UnitOfWorkFactory
from applicability_engine.settings import ApplicabilityEngineSettings
from domain_kernel.erasure import ErasedTenants
from py_common.idempotency import IdempotencyStore


@dataclass(frozen=True, slots=True)
class Readers:
    """Where decisions are computed from: HTTP clients in the app, memory fakes in tests."""

    profiles: ProfileReader
    rulebook: RulebookReader


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: ApplicabilityEngineSettings
    unit_of_work: UnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    idempotency: IdempotencyStore
    evaluate: EvaluateRule
    list_decisions: ListDecisions
    read_decision: ReadDecision
    list_review_items: ListReviewItems
    resolve_review_item: ResolveReviewItem
    list_fan_outs: ListFanOuts
    read_fan_out: ReadFanOut
    pause_fan_out: PauseFanOut
    resume_fan_out: ResumeFanOut
    cancel_fan_out: CancelFanOut
    read_hold: ReadHold
    set_hold: SetHold
    release_hold: ReleaseHold
    read_change_impact: ReadChangeImpact
    dry_run: DryRun
    export_data: ExportTenantData
    erased_tenants: ErasedTenants
    """The tenants the engine has erased: its routes answer them 410."""
