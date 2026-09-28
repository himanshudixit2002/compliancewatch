"""Errors of the profile service, with stable problem type slugs."""

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
