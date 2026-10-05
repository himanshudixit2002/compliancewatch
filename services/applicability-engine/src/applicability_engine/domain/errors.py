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
    title = "Rule version not found for applicability"

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


class ReviewItemNotFoundError(DomainError, LookupError):
    type_slug = "applicability-review-item-not-found"
    title = "Review item not found"

    def __init__(self, item_id: str) -> None:
        super().__init__(f"review item {item_id} does not exist for this tenant")
        self.item_id = item_id


class ReviewItemResolvedError(DomainError, ValueError):
    """An item is resolved once; a later decision of its business and rule version opens a new
    one when it needs review."""

    type_slug = "applicability-review-item-resolved"
    title = "Review item is already resolved"

    def __init__(self, item_id: str) -> None:
        super().__init__(f"review item {item_id} is already resolved")
        self.item_id = item_id


class FanOutNotFoundError(DomainError, LookupError):
    type_slug = "applicability-fan-out-not-found"
    title = "Fan-out not found"

    def __init__(self, rule_version_id: str) -> None:
        super().__init__(f"no fan-out of rule version {rule_version_id} exists")
        self.rule_version_id = rule_version_id


class FanOutStateError(DomainError, ValueError):
    """A control the run's status does not allow: pausing a run that is not running or held,
    resuming one that is not paused, or anything on a run that has finished."""

    type_slug = "applicability-fan-out-state"
    title = "Fan-out cannot do that now"

    def __init__(self, rule_version_id: str, status: str, to: str) -> None:
        super().__init__(f"the fan-out of {rule_version_id} is {status}; it cannot become {to}")
        self.rule_version_id = rule_version_id
        self.status = status
        self.to = to
