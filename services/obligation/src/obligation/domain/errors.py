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
    type_slug = "rule-version-not-found"
    title = "Rule version not found"

    def __init__(self, rule_version_id: str) -> None:
        super().__init__(f"the rulebook has no rule version {rule_version_id}")
        self.rule_version_id = rule_version_id


class RulebookUnavailableError(DomainError, ConnectionError):
    """The rulebook could not answer now; another try may succeed."""

    type_slug = "rulebook-unavailable"
    title = "Rulebook unavailable"
