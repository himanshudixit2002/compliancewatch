"""Alignment: which canonical entity a mention names, decided without a model.

A mention resolves when its proposed name is an entity's canonical name, or the one alias of
exactly one entity of its type. Anything else goes to review with the reason: nothing is
created on the fly (ADR-017) and nothing is matched fuzzily. A section or rule must name its
statute (``39(1)@cgst-act``): section 16 of the CGST Act is not section 16 of the IGST Act.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from domain_kernel.ids import CanonicalEntityId
from domain_kernel.knowledge import EntityType

_PROVISIONS = frozenset({EntityType.SECTION, EntityType.RULE})


class ReviewReason(StrEnum):
    NO_MATCH = "no_match"
    AMBIGUOUS_ALIAS = "ambiguous_alias"
    EMPTY_NAME = "empty_name"
    UNQUALIFIED = "unqualified"


class MatchKind(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"


@dataclass(frozen=True, slots=True)
class Resolved:
    entity_id: CanonicalEntityId
    match: MatchKind


@dataclass(frozen=True, slots=True)
class Unresolved:
    reason: ReviewReason


class EntityLookup(Protocol):
    def by_name(self, entity_type: EntityType, name: str) -> CanonicalEntityId | None: ...

    def by_alias(self, entity_type: EntityType, alias: str) -> Sequence[CanonicalEntityId]: ...


def resolve(
    entity_type: EntityType, proposed_name: str, lookup: EntityLookup
) -> Resolved | Unresolved:
    """The entity ``proposed_name`` names, or why a person has to decide."""
    if not proposed_name:
        return Unresolved(ReviewReason.EMPTY_NAME)
    if entity_type in _PROVISIONS and "@" not in proposed_name:
        return Unresolved(ReviewReason.UNQUALIFIED)
    exact = lookup.by_name(entity_type, proposed_name)
    if exact is not None:
        return Resolved(exact, MatchKind.EXACT)
    aliased = list(dict.fromkeys(lookup.by_alias(entity_type, proposed_name)))
    if len(aliased) == 1:
        return Resolved(aliased[0], MatchKind.ALIAS)
    if aliased:
        return Unresolved(ReviewReason.AMBIGUOUS_ALIAS)
    return Unresolved(ReviewReason.NO_MATCH)
