"""Errors of the profile service, with stable problem type slugs."""

from collections.abc import Mapping

from domain_kernel.errors import DomainError


class ProfileNodeNotFoundError(DomainError, LookupError):
    type_slug = "profile-node-not-found"
    title = "Profile node not found"

    def __init__(self, node_id: str) -> None:
        super().__init__(f"profile node {node_id} does not exist for this tenant")
        self.node_id = node_id


class InvalidHierarchyError(DomainError, ValueError):
    type_slug = "profile-hierarchy-invalid"
    title = "Profile hierarchy is invalid"


class AttributeLevelMismatchError(DomainError, ValueError):
    type_slug = "profile-attribute-level-mismatch"
    title = "Attribute belongs to another level"

    def __init__(self, key: str, attribute_level: str, node_level: str) -> None:
        super().__init__(
            f"attribute {key!r} lives at the {attribute_level} level; this node is a {node_level}"
        )
        self.key = key


class FinancialYearRequiredError(DomainError, ValueError):
    type_slug = "profile-financial-year-required"
    title = "Financial year required"

    def __init__(self, key: str) -> None:
        super().__init__(f"attribute {key!r} is stated per financial year; give as_of_fy")
        self.key = key


class TenantRequiredError(DomainError, PermissionError):
    type_slug = "tenant-required"
    title = "Tenant required"

    def __init__(self) -> None:
        super().__init__("the request names no tenant (x-tenant-id header)")


class BusinessIdentifierRequiredError(DomainError, ValueError):
    type_slug = "profile-business-identifier-required"
    title = "Business needs a PAN or GSTIN"

    def __init__(self) -> None:
        super().__init__(
            "a business is created from its GSTIN or, without one, its PAN; give either"
        )


class RegistrationAmbiguousError(DomainError, ValueError):
    type_slug = "profile-registration-ambiguous"
    title = "Registration must be named"

    def __init__(self, key: str, level: str, count: int) -> None:
        where = f"has no {level}" if count == 0 else f"has {count}"
        super().__init__(
            f"attribute {key!r} belongs to one {level} and the business {where}; name the node "
            "with node_id"
        )
        self.key = key


class NotABusinessError(DomainError, LookupError):
    type_slug = "profile-node-not-a-business"
    title = "Profile node is not a business"

    def __init__(self, node_id: str) -> None:
        super().__init__(
            f"profile node {node_id} is a registration or location; a business is a legal entity"
        )
        self.node_id = node_id


class PlanLimitReachedError(DomainError):
    """The tenant's plan allows no more GSTIN registrations (402). The body carries the limit
    and how many the tenant holds (``limit``, ``used``), and never the GSTIN asked for."""

    type_slug = "profile-plan-limit-reached"
    title = "Plan registration limit reached"

    def __init__(self, *, limit: int, used: int) -> None:
        self.limit = limit
        self.used = used
        self.problem_extensions: Mapping[str, object] = {"limit": limit, "used": used}
        super().__init__(
            f"the plan allows {limit} GSTIN registration(s) and the tenant holds {used}; "
            "upgrade the plan to add another"
        )
