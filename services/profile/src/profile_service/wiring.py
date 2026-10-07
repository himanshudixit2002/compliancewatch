"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from domain_kernel.erasure import ErasedTenants
from domain_kernel.ontology import Ontology, OntologyWording
from profile_service.application.attributes import (
    BuildSnapshot,
    ConfirmFinancialYear,
    NextQuestion,
    SetAttributes,
)
from profile_service.application.businesses import (
    AddRegistration,
    CreateBusiness,
    ListBusinesses,
    ReadBusiness,
    UpdateBusiness,
)
from profile_service.application.export import ExportTenantData
from profile_service.application.onboarding import OnboardingChecklist
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.repository import UnitOfWorkFactory
from profile_service.settings import ProfileSettings
from py_common.idempotency import IdempotencyStore


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: ProfileSettings
    ontology: Ontology
    wording: OntologyWording
    unit_of_work: UnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    idempotency: IdempotencyStore
    register: RegisterNodes
    set_attributes: SetAttributes
    next_question: NextQuestion
    build_snapshot: BuildSnapshot
    confirm_financial_year: ConfirmFinancialYear
    prefill: PrefillFromGstin
    create_business: CreateBusiness
    update_business: UpdateBusiness
    read_business: ReadBusiness
    list_businesses: ListBusinesses
    add_registration: AddRegistration
    onboarding: OnboardingChecklist
    export_data: ExportTenantData
    erased_tenants: ErasedTenants
    """The tenants the profile has erased: its routes answer them 410."""
