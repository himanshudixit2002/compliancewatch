"""The onboarding checklist of one business, for the financial year of today's date in India."""

from collections.abc import Callable
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import Ontology
from profile_service.application.attributes import financial_year_in_india
from profile_service.application.businesses import load_business
from profile_service.domain.onboarding import Checklist, build_checklist
from profile_service.domain.repository import UnitOfWorkFactory


class OnboardingChecklist:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        ontology: Ontology,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ontology = ontology
        self._clock = clock

    def run(self, tenant_id: TenantId, business_id: BusinessId) -> Checklist:
        """Per-year questions are asked for the financial year today falls in, in IST."""
        fy = financial_year_in_india(self._clock())
        with self._unit_of_work(tenant_id) as uow:
            business = load_business(uow, business_id)
        return build_checklist(business.entity, business.registrations, self._ontology, fy)
