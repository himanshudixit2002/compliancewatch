"""The rolling window (ADR-015): once a day, the periods that entered the window since the last
run get their obligations.

A decision that applies materialises the period it was made in and the next one. Time moves the
window on: ``RollWindow.run`` visits every tenant of the tenant directory (or those named in
``only``) and, for each business whose latest decision of a recurring rule version applies
(``obligation_decision``), materialises the window as of today in India with
``MaterialiseObligations``. That is idempotent on (business, rule version, period), so it creates
exactly the periods that entered the window since a decision or a run last made them, and a
period closed meanwhile stays closed.

Each tenant takes three steps, so no unit of work is open while the rulebook is read: a unit
reads the decisions that apply, the reader reads their rule versions (a one-off version is left
alone: its obligation was made with its decision), and a second unit puts each version through
the guard (``guard.admit``: a withdrawn or uncited version makes nothing, a superseded one only
the periods it still governs) and materialises. A version withdrawn, or no longer in force
today, is passed over without a word: its decisions stay on record, and refusing its periods
every day would only be noise. A tenant that fails is reported to ``on_failure`` and the run goes
on with the next one; the next run tries it again.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import date, datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import ObligationId, RuleVersionId, TenantId
from obligation.application.guard import admit
from obligation.application.materialise import IST, MaterialiseRequest, materialise_in
from obligation.domain.ports import RuleVersionReader
from obligation.domain.repository import TenantDirectory, UnitOfWorkFactory
from obligation.domain.rule_versions import Refusal, RuleVersionRead, RuleVersionRef

FailureHandler = Callable[[TenantId, Exception], None]


@dataclass(frozen=True, slots=True)
class Rolled:
    """What one run did: tenants visited, obligations made, and what the guard kept from being
    made, by reason (one count per business and version, or per period refused)."""

    tenants: int = 0
    created: tuple[ObligationId, ...] = ()
    refused: tuple[tuple[Refusal, int], ...] = ()
    failed: tuple[TenantId, ...] = ()


class RollWindow:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        tenants: TenantDirectory,
        rules: RuleVersionReader,
        *,
        window: int = 2,
        clock: Callable[[], datetime] = utc_now,
        on_failure: FailureHandler | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._tenants = tenants
        self._rules = rules
        self._window = window
        self._clock = clock
        self._on_failure = on_failure

    def run(self, *, only: Collection[TenantId] | None = None) -> Rolled:
        now = self._clock()
        visited = 0
        created: list[ObligationId] = []
        refused: dict[Refusal, int] = {}
        failed: list[TenantId] = []
        for tenant_id in self._tenants.tenants():
            if only is not None and tenant_id not in only:
                continue
            visited += 1
            try:
                made, kept_back = self._roll(tenant_id, now)
            except Exception as exc:
                failed.append(tenant_id)
                if self._on_failure is None:
                    raise
                self._on_failure(tenant_id, exc)
                continue
            created.extend(made)
            for reason, count in kept_back.items():
                refused[reason] = refused.get(reason, 0) + count
        return Rolled(visited, tuple(created), tuple(sorted(refused.items())), tuple(failed))

    def _roll(
        self, tenant_id: TenantId, now: datetime
    ) -> tuple[list[ObligationId], dict[Refusal, int]]:
        with self._unit_of_work(tenant_id) as uow:
            applying = list(uow.decisions.applying())
        reads: dict[RuleVersionId, RuleVersionRead] = {}
        for rule_version_id in sorted({d.rule_version_id for d in applying}, key=str):
            read = self._rules.read(rule_version_id)
            if read is not None and read.snapshot.recurrence is not None:
                reads[rule_version_id] = read
        created: list[ObligationId] = []
        refused: dict[Refusal, int] = {}
        as_of = now.astimezone(IST).date()
        with self._unit_of_work(tenant_id) as uow:
            for decision in applying:
                read = reads.get(decision.rule_version_id)
                if read is None:
                    continue
                admission = admit(uow, read.ref)
                if _retired(admission.ref, as_of) or admission.refusal is Refusal.RULE_WITHDRAWN:
                    continue
                if admission.refusal is not None:
                    refused[admission.refusal] = refused.get(admission.refusal, 0) + 1
                    continue
                result = materialise_in(
                    uow,
                    MaterialiseRequest(
                        tenant_id=tenant_id,
                        business_id=decision.business_id,
                        decision_id=decision.decision_id,
                        rule=read.snapshot,
                        as_of=as_of,
                        ref=admission.ref,
                        profile_version=decision.profile_version,
                    ),
                    window=self._window,
                    now=now,
                )
                created.extend(result.created)
                if result.refused:
                    superseded = Refusal.RULE_SUPERSEDED
                    refused[superseded] = refused.get(superseded, 0) + len(result.refused)
        return created, refused


def _retired(ref: RuleVersionRef, as_of: date) -> bool:
    """Whether the version stopped governing before ``as_of``: every period of the window is
    the newer version's, so there is nothing to roll and nothing unusual to report."""
    return ref.effective_to is not None and as_of >= ref.effective_to
