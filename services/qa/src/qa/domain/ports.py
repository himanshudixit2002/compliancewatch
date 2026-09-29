"""What the qa service needs from other services and from tracing, as protocols. The adapters
live in ``infrastructure`` (HTTP, OpenTelemetry) and ``testing`` (memory).

Readers raise ``DependencyUnavailableError`` when the service does not answer or fails; a thing
that does not exist is ``None`` or an empty tuple, never an error.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from datetime import date
from typing import Protocol

from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, CanonicalEntityId, ClauseId, RuleVersionId, TenantId
from domain_kernel.knowledge import EntityType
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.vectors import Vector
from qa.domain.records import (
    ClauseRecord,
    EntityResolution,
    ObligationRecord,
    QueryEmbedding,
    Relation,
    RuleVersion,
    RuleVersionDetail,
    SearchHit,
)

type AttributeValue = str | int | float | bool
"""What a span attribute may hold: ids, counts and codes, never question or regulator text."""


class RulebookReader(Protocol):
    """The rulebook's open read API."""

    def rules_in_force(
        self, as_of: date, *, rule_key: str | None = None, regulator: str | None = None
    ) -> tuple[RuleVersion, ...]:
        """Published or superseded versions with ``as_of`` in their effective period, by key."""
        ...

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionDetail | None:
        """One version in any status with its citations."""
        ...

    def resolve_entity(self, entity_type: EntityType, name: str) -> EntityResolution: ...

    def entity_clauses(
        self, entity_id: CanonicalEntityId, *, as_of: date | None, limit: int
    ) -> tuple[ClauseRecord, ...]:
        """Clauses that mention the entity, newest document first."""
        ...

    def relations(
        self,
        *,
        from_rule_version_id: RuleVersionId | None = None,
        to_rule_version_id: RuleVersionId | None = None,
        to_entity_id: CanonicalEntityId | None = None,
    ) -> tuple[Relation, ...]:
        """Relations from versions that have been published; name at least one end."""
        ...

    def clause(self, clause_id: ClauseId) -> ClauseRecord | None: ...


class ClauseSearch(Protocol):
    """The rulebook's hybrid clause search."""

    def search(
        self,
        text: str,
        *,
        vector: Vector | None,
        model: str | None,
        as_of: date | None,
        k: int,
    ) -> tuple[SearchHit, ...]:
        """Full text and, with a vector and its model, vectors, fused by reciprocal rank."""
        ...


class Embedder(Protocol):
    """The question's vector through the llm-gateway's retrieval feature."""

    def embed(
        self, text: str, *, tenant: TenantId | None, metadata: Mapping[str, str]
    ) -> QueryEmbedding: ...


class ProfileReader(Protocol):
    def snapshot(
        self, tenant: TenantId, business: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        """The attributes of a business node for one financial year, inherited down its
        lineage; ``None`` when the tenant has no such node."""
        ...


class ObligationReader(Protocol):
    def obligations(
        self,
        tenant: TenantId,
        business: BusinessId,
        *,
        due_from: date | None = None,
        due_to: date | None = None,
        rule_version_id: RuleVersionId | None = None,
    ) -> tuple[ObligationRecord, ...]:
        """A business's obligations, due date first; both window ends are days in India,
        included."""
        ...


class Span(Protocol):
    def set_attribute(self, key: str, value: AttributeValue) -> None: ...


class Tracer(Protocol):
    def span(
        self, name: str, attributes: Mapping[str, AttributeValue] | None = None
    ) -> AbstractContextManager[Span]:
        """A span around the block; an exception leaving it marks the span failed."""
        ...
