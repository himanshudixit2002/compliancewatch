"""Read a business's obligations for the Q&A service, the product UI and the public API.

``ListObligations`` returns every obligation of one business in any status, optionally only the
ones due inside a window of days in India and of one rule version, due date first. It reads in
the tenant's unit of work, so row-level security scopes it to that tenant; at most
``MAX_OBLIGATIONS`` come back.

``ListBusinessObligations`` serves the public API's list, a page at a time: the business's
obligations in some statuses and due inside a window, by due date (none last) and id, each with
what the service keeps of its rule version (title, rule key, seed status, the approvers and the
verified citations), or None for a version not kept yet. It reads in the tenant's unit of work
too. A page with nothing on it asks the profile service, after the unit of work has closed,
whether the business is a node of the tenant at all: another tenant's business, or none, is
``BusinessNotFoundError``. A business with obligations on the page is the tenant's, so the
profile service is not asked then.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.status import ObligationStatus
from obligation.application.materialise import IST
from obligation.domain.errors import BusinessNotFoundError
from obligation.domain.model import DueWindow, Obligation
from obligation.domain.ports import ProfileNodes
from obligation.domain.repository import ListingAfter, UnitOfWorkFactory
from obligation.domain.rule_versions import RuleVersionRef

MAX_OBLIGATIONS = 500
MAX_PAGE = 201
"""The most rows one page reads: the public list's 200, and the one after that says whether a
next page exists."""


@dataclass(frozen=True, slots=True)
class ObligationQuery:
    tenant_id: TenantId
    business_id: BusinessId
    window: DueWindow = field(default_factory=DueWindow)
    rule_version_id: RuleVersionId | None = None
    limit: int = MAX_OBLIGATIONS


class ListObligations:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, query: ObligationQuery) -> tuple[Obligation, ...]:
        due_after, due_before = query.window.bounds(IST)
        with self._unit_of_work(query.tenant_id) as uow:
            return tuple(
                uow.obligations.list_for_business(
                    query.business_id,
                    due_after=due_after,
                    due_before=due_before,
                    rule_version_id=query.rule_version_id,
                    limit=min(max(query.limit, 1), MAX_OBLIGATIONS),
                )
            )


@dataclass(frozen=True, slots=True)
class BusinessObligationsQuery:
    """One page of a business's obligations: of ``statuses`` (every status when empty), due
    inside ``window``, after ``after``, at most ``limit``."""

    tenant_id: TenantId
    business_id: BusinessId
    limit: int
    window: DueWindow = field(default_factory=DueWindow)
    statuses: frozenset[ObligationStatus] = frozenset()
    after: ListingAfter | None = None


@dataclass(frozen=True, slots=True)
class ListedObligation:
    """An obligation on a page with the facts kept of its rule version: None when the service
    has not kept the version yet (an obligation made before it kept them)."""

    obligation: Obligation
    ref: RuleVersionRef | None


class ListBusinessObligations:
    def __init__(self, unit_of_work: UnitOfWorkFactory, profiles: ProfileNodes) -> None:
        self._unit_of_work = unit_of_work
        self._profiles = profiles

    def run(self, query: BusinessObligationsQuery) -> Sequence[ListedObligation]:
        """The page, in order. Raises ``BusinessNotFoundError`` when it is empty and the tenant
        has no such business, and ``ProfileUnavailableError`` when the profile service cannot
        say."""
        due_after, due_before = query.window.bounds(IST)
        with self._unit_of_work(query.tenant_id) as uow:
            found = uow.obligations.page_for_business(
                query.business_id,
                statuses=query.statuses,
                due_after=due_after,
                due_before=due_before,
                after=query.after,
                limit=min(max(query.limit, 1), MAX_PAGE),
            )
            refs = {
                version: uow.rule_versions.get(version)
                for version in dict.fromkeys(obligation.rule_version_id for obligation in found)
            }
        if not found and not self._profiles.exists(query.tenant_id, query.business_id):
            raise BusinessNotFoundError(str(query.business_id))
        return [
            ListedObligation(obligation, refs[obligation.rule_version_id]) for obligation in found
        ]
