"""The entity review queue: list open groups, decide one.

A group is every mention that shares an entity type and a proposed name. Creating the entity
or adding the name as an alias of an existing one resolves every open mention of the group into
the index, and points open relation candidates that target the name at the entity, all in one
transaction. A name that cannot be an alias (empty, or a section or rule with no statute) is
linked to the chosen entity for these mentions only.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CanonicalEntityId
from domain_kernel.knowledge import EntityType
from rulebook.application.alignment import Clock, default_clock
from rulebook.domain.errors import (
    EntityTypeMismatchError,
    NonCanonicalNameError,
    ReviewGroupClosedError,
    ReviewGroupNotFoundError,
    UnknownEntityError,
)
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.domain.review import (
    EntityRejectReason,
    MentionDecision,
    MentionGroup,
    Resolution,
    ReviewStatus,
)

_PROVISIONS = frozenset({EntityType.SECTION, EntityType.RULE})
MAX_PAGE = 200


@dataclass(frozen=True, slots=True)
class GroupDecision:
    status: ReviewStatus
    resolution: Resolution | None
    entity_id: CanonicalEntityId | None
    items_closed: int
    relation_targets_updated: int


class ListMentionGroups:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        entity_type: EntityType | None = None,
        limit: int = 50,
        after: tuple[str, str] | None = None,
    ) -> Sequence[MentionGroup]:
        with self._unit_of_work() as uow:
            return uow.reviews.open_groups(entity_type, min(max(limit, 1), MAX_PAGE), after)


class DecideMentionGroup:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        entity_type: EntityType,
        proposed_name: str,
        decision: MentionDecision,
        *,
        decided_by: str,
        entity_id: CanonicalEntityId | None = None,
        reject_reason: EntityRejectReason | None = None,
        note: str = "",
    ) -> GroupDecision:
        now = self._clock()
        with self._unit_of_work() as uow:
            items = uow.reviews.lock_group(entity_type, proposed_name)
            if not items:
                raise ReviewGroupNotFoundError(
                    f"no review items for {entity_type.value} {proposed_name!r}"
                )
            open_items = [item for item in items if item.status is ReviewStatus.OPEN]
            if not open_items:
                raise ReviewGroupClosedError(
                    f"every item for {entity_type.value} {proposed_name!r} is decided"
                )
            if decision is MentionDecision.REJECT:
                if reject_reason is None:
                    raise InvariantViolationError("a rejection needs a reason")
                for item in open_items:
                    uow.reviews.save(
                        item.reject(reject_reason, decided_by=decided_by, at=now, note=note)
                    )
                return GroupDecision(ReviewStatus.REJECTED, None, None, len(open_items), 0)

            if decision is MentionDecision.CREATE_ENTITY:
                if not _can_name(entity_type, proposed_name):
                    raise NonCanonicalNameError(
                        f"{proposed_name!r} cannot name a {entity_type.value}; add it to an "
                        "existing entity instead"
                    )
                target, created = uow.entities.create_or_get(entity_type, proposed_name)
                resolution = Resolution.CREATED if created else Resolution.MATCHED
            else:
                if entity_id is None:
                    raise InvariantViolationError("adding an alias needs the entity it belongs to")
                found = uow.entities.get(entity_id)
                if found is None:
                    raise UnknownEntityError(str(entity_id))
                if found[0] is not entity_type:
                    raise EntityTypeMismatchError(
                        f"entity {entity_id} is a {found[0].value}, the mentions are "
                        f"{entity_type.value}"
                    )
                target = entity_id
                aliased = _can_name(entity_type, proposed_name) and uow.entities.add_alias(
                    entity_id, proposed_name
                )
                resolution = Resolution.ALIASED if aliased else Resolution.MATCHED

            for item in open_items:
                uow.mentions.add(
                    item.clause_id,
                    target,
                    item.mention_text,
                    item.span_start,
                    item.span_end,
                    method="grammar",
                    extractor=item.extractor,
                )
                uow.reviews.save(
                    item.resolve(target, resolution, decided_by=decided_by, at=now, note=note)
                )
            updated = uow.candidates.set_target_entity(entity_type, proposed_name, target)
            return GroupDecision(
                ReviewStatus.RESOLVED, resolution, target, len(open_items), updated
            )


def _can_name(entity_type: EntityType, name: str) -> bool:
    """Whether ``name`` can be an entity's canonical name or alias."""
    return bool(name) and (entity_type not in _PROVISIONS or "@" in name)
