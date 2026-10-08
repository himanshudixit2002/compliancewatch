"""What the API layer gets from the composition root, typed by protocols and use cases."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from domain_kernel.erasure import ErasedTenants
from identity.application.audit import ReadAuditTrail
from identity.application.billing import ReceiveBillingWebhook, StartSubscription
from identity.application.channel_consents import ChannelConsentStatus, RecordChannelConsent
from identity.application.consents import ConsentStatus, RecordConsent
from identity.application.data_requests import (
    ExportTenantData,
    ListDataRequests,
    ReadDataRequest,
    RequestDeletion,
    RequestExport,
)
from identity.application.entitlements import ReadEntitlements
from identity.application.erasure import CheckErasure
from identity.application.sessions import ExchangeSession, IssueServiceToken
from identity.application.tenancy import (
    ChangeRoles,
    CreateTenant,
    CurrentUser,
    DisableUser,
    InviteUser,
    ListUsers,
    ReadMembership,
)
from identity.domain.channel_consent import ChannelUnitOfWorkFactory
from identity.domain.data_requests import DataRequestDirectory
from identity.domain.provider import DevIdentityProvider, IdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.settings import IdentitySettings
from py_common.auth import KeySet
from py_common.idempotency import IdempotencyStore


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: IdentitySettings
    unit_of_work: UnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    record_consent: RecordConsent
    consent_status: ConsentStatus
    channel_unit_of_work: ChannelUnitOfWorkFactory
    record_channel_consent: RecordChannelConsent
    channel_consent_status: ChannelConsentStatus
    billing_enabled: bool
    start_subscription: StartSubscription | None
    receive_billing_webhook: ReceiveBillingWebhook | None
    keys: KeySet
    provider: IdentityProvider
    dev_provider: DevIdentityProvider | None
    """The fake provider, for the dev sign-in route: set only with it in local and test."""
    exchange_session: ExchangeSession
    issue_service_token: IssueServiceToken
    create_tenant: CreateTenant
    current_user: CurrentUser
    list_users: ListUsers
    read_membership: ReadMembership
    invite_user: InviteUser
    change_roles: ChangeRoles
    disable_user: DisableUser
    read_audit_trail: ReadAuditTrail
    read_entitlements: ReadEntitlements
    idempotency: IdempotencyStore
    request_export: RequestExport
    request_deletion: RequestDeletion
    list_data_requests: ListDataRequests
    read_data_request: ReadDataRequest
    export_tenant_data: ExportTenantData
    data_request_directory: DataRequestDirectory
    check_erasure: CheckErasure
    erased_tenants: ErasedTenants
    """The tenants identity has erased: its tenant routes answer them 410."""
