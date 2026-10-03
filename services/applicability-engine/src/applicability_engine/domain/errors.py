"""Errors of the applicability-engine service, with stable problem type slugs."""

from domain_kernel.errors import DomainError


class ApplicabilityTenantRequiredError(DomainError, PermissionError):
    type_slug = "applicability-tenant-required"
    title = "Tenant required for applicability decisions"

    def __init__(self) -> None:
        super().__init__("the request names no tenant (x-tenant-id header)")


class BusinessNotFoundError(DomainError, LookupError):
    type_slug = "applicability-business-not-found"
    title = "Business not found"

    def __init__(self, business_id: str) -> None:
        super().__init__(f"the profile service has no business {business_id} for this tenant")
        self.business_id = business_id


class RuleVersionNotFoundError(DomainError, LookupError):
    type_slug = "applicability-rule-version-not-found"
    title = "Rule version not found"

    def __init__(self, rule_version_id: str) -> None:
        super().__init__(f"the rulebook has no rule version {rule_version_id}")
        self.rule_version_id = rule_version_id


class RuleVersionNotPublishedError(DomainError, ValueError):
    """Only a published version is in force; a decision on a draft would let the obligation
    service create obligations for a rule nobody has approved."""

    type_slug = "applicability-rule-version-not-published"
    title = "Rule version is not published"

    def __init__(self, rule_version_id: str, status: str) -> None:
        super().__init__(f"rule version {rule_version_id} is {status}, not published")
        self.rule_version_id = rule_version_id
        self.status = status


class DecisionNotFoundError(DomainError, LookupError):
    type_slug = "applicability-decision-not-found"
    title = "Decision not found"

    def __init__(self, decision_id: str) -> None:
        super().__init__(f"decision {decision_id} does not exist for this tenant")
        self.decision_id = decision_id


class DependencyUnavailableError(DomainError):
    """The profile service or the rulebook did not answer, refused the call, or answered with
    something that is not the shape of its contract."""

    type_slug = "applicability-dependency-unavailable"
    title = "A service the decision needs is unavailable"
