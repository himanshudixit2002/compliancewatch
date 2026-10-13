"""Errors of the obligation service, with stable problem type slugs."""

from domain_kernel.errors import DomainError


class ObligationNotFoundError(DomainError, LookupError):
    type_slug = "obligation-not-found"
    title = "Obligation not found"

    def __init__(self, obligation_id: str) -> None:
        super().__init__(f"obligation {obligation_id} does not exist for this tenant")
        self.obligation_id = obligation_id


class ObligationClosedError(DomainError, ValueError):
    type_slug = "obligation-closed"
    title = "Obligation is closed"

    def __init__(self, obligation_id: str, status: str) -> None:
        super().__init__(f"obligation {obligation_id} is {status} and cannot change")
        self.obligation_id = obligation_id
        self.status = status


class ObligationTenantRequiredError(DomainError, PermissionError):
    type_slug = "obligation-tenant-required"
    title = "Tenant required for obligations"

    def __init__(self) -> None:
        super().__init__("the request names no tenant (x-tenant-id header)")


class ObligationWindowInvalidError(DomainError, ValueError):
    type_slug = "obligation-window-invalid"
    title = "Due window is invalid"


class RuleVersionNotFoundError(DomainError, LookupError):
    type_slug = "obligation-rule-version-not-found"
    title = "Rule version not found for obligations"

    def __init__(self, rule_version_id: str) -> None:
        super().__init__(f"the rulebook has no rule version {rule_version_id}")
        self.rule_version_id = rule_version_id


class RulebookUnavailableError(DomainError, ConnectionError):
    """The rulebook could not answer now; another try may succeed."""

    type_slug = "rulebook-unavailable"
    title = "Rulebook unavailable"


class AssigneeNotMemberError(DomainError, ValueError):
    """The user named as the assignee is not an active user of the tenant."""

    type_slug = "obligation-assignee-unknown"
    title = "Assignee is not a user of the tenant"

    def __init__(self, user_id: str) -> None:
        super().__init__(f"user {user_id} is not an active user of this tenant")
        self.user_id = user_id


class IdentityUnavailableError(DomainError, ConnectionError):
    """The identity service could not say whether a user belongs to the tenant now; another try
    may succeed."""

    type_slug = "identity-unavailable"
    title = "Identity service unavailable"


class BusinessNotFoundError(DomainError, LookupError):
    """The tenant has no profile node with this id: no business, registration or location."""

    type_slug = "obligation-business-not-found"
    title = "Business not found for obligations"

    def __init__(self, business_id: str) -> None:
        super().__init__(f"business {business_id} is not a profile node of this tenant")
        self.business_id = business_id


class ProfileUnavailableError(DomainError, ConnectionError):
    """The profile service could not say whether a business belongs to the tenant now; another
    try may succeed."""

    type_slug = "profile-unavailable"
    title = "Profile service unavailable"


class ErrorReportsDisabledError(DomainError, LookupError):
    """The flag ``obligation.error_reports`` is off for the tenant: the report route does not
    exist for it (404) and nothing is stored."""

    type_slug = "obligation-error-reports-disabled"
    title = "Error reports are not available"

    def __init__(self) -> None:
        super().__init__("reporting an error in an obligation is not available for this tenant")


class ErrorReportNotFoundError(DomainError, LookupError):
    type_slug = "obligation-error-report-not-found"
    title = "Error report not found"

    def __init__(self, report_id: str) -> None:
        super().__init__(f"error report {report_id} does not exist for this tenant")
        self.report_id = report_id


class ErrorReportDecidedError(DomainError, ValueError):
    """The report was decided already: a decision is final."""

    type_slug = "obligation-error-report-decided"
    title = "Error report already decided"

    def __init__(self, report_id: str, status: str) -> None:
        super().__init__(f"error report {report_id} is {status} and cannot be decided again")
        self.report_id = report_id
        self.status = status
