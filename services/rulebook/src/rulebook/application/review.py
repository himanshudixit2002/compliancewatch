"""The entity review queue: list open groups, decide one.

A group is every mention that shares an entity type and a proposed name. Creating the entity
or adding the name as an alias of an existing one resolves every open mention of the group into
the index, and points open relation candidates that target the name at the entity, all in one
transaction.

A name that cannot name an entity (empty, or a section or rule with no statute) means different
things in different documents: "section 16" of one notification is not "section 16" of another.
Such a group is decided mention by mention: the decision names the review items it covers
(``review_ids``), links only those mentions to the chosen entity, adds no alias, and points only
the candidates whose target is one of those mentions at the entity.

A decision writes one ``entity_review.decided`` audit entry in its transaction
(``rulebook.application.audit``). A group has no id of its own, so the entry's subject id is
the group's key, ``<entity_type>:<proposed_name>`` (``group_key``); the entry's ``after`` holds
the decision, the entity it chose, how many open mentions it closed and, for a decision by
mention, the review ids.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from domain_kernel.audit import MAX_SUBJECT_ID_CHARS
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CanonicalEntityId
from domain_kernel.knowledge import EntityType
from rulebook.application.alignment import Clock, default_clock
from rulebook.application.audit import actor_for, entry
from rulebook.domain.errors import (
    EntityTypeMismatchError,
    NonCanonicalNameError,
    ReviewGroupClosedError,
    ReviewGroupNotFoundError,
    UnknownEntityError,
)
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory
from rulebook.domain.review import (
    EntityRejectReason,
    EntityReviewItem,
    MentionDecision,
    MentionGroup,
    Resolution,
    ReviewQueueStats,
    ReviewStatus,
)

_PROVISIONS = frozenset({EntityType.SECTION, EntityType.RULE})
MAX_PAGE = 200
DECIDED_ACTION: Final = "entity_review.decided"
SUBJECT: Final = "entity_review"


def group_key(entity_type: EntityType, proposed_name: str) -> str:
    """The audit subject id of a mention group: ``<entity_type>:<proposed_name>``, or, for a name
    too long for a subject id, ``<entity_type>:sha256:<digest of the name>``."""
    key = f"{entity_type.value}:{proposed_name}"
    if len(key) <= MAX_SUBJECT_ID_CHARS:
        return key
    digest = hashlib.sha256(proposed_name.encode()).hexdigest()
    return f"{entity_type.value}:sha256:{digest}"


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


class ListGroupItems:
    """Every open mention of one group, for decisions that must name their items."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, entity_type: EntityType, proposed_name: str) -> tuple[EntityReviewItem, ...]:
        with self._unit_of_work() as uow:
            return uow.reviews.group_items(entity_type, proposed_name)[:MAX_PAGE]


class ReadReviewQueueStats:
    """How many mentions wait for an analyst, per entity type, and since when: the numbers
    behind the review queue alerts."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self) -> ReviewQueueStats:
        with self._unit_of_work() as uow:
            return uow.reviews.queue_stats()


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
        review_ids: Sequence[UUID] | None = None,
    ) -> GroupDecision:
        nameable = _can_name(entity_type, proposed_name)
        if not nameable and not review_ids:
            raise InvariantViolationError(
                f"{proposed_name!r} does not name one {entity_type.value} across documents; "
                "decide its mentions by review_ids"
            )
        now = self._clock()
        with self._unit_of_work() as uow:
            items = uow.reviews.lock_group(entity_type, proposed_name)
            if not items:
                raise ReviewGroupNotFoundError(
                    f"no review items for {entity_type.value} {proposed_name!r}"
                )
            if review_ids:
                wanted = set(review_ids)
                items = tuple(item for item in items if item.review_id in wanted)
                if len(items) != len(wanted):
                    raise ReviewGroupNotFoundError(
                        f"some review_ids are not in {entity_type.value} {proposed_name!r}"
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
                result = GroupDecision(ReviewStatus.REJECTED, None, None, len(open_items), 0)
                _audit(
                    uow,
                    entity_type,
                    proposed_name,
                    decision,
                    result,
                    decided_by=decided_by,
                    at=now,
                    note=note,
                    reject_reason=reject_reason,
                    review_ids=review_ids,
                )
                return result

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
                aliased = nameable and uow.entities.add_alias(entity_id, proposed_name)
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
            updated = sum(
                uow.candidates.set_target_entity_at(
                    item.clause_id, item.span_start, entity_type, target
                )
                for item in open_items
            )
            if nameable:
                updated += uow.candidates.set_target_entity(entity_type, proposed_name, target)
            result = GroupDecision(
                ReviewStatus.RESOLVED, resolution, target, len(open_items), updated
            )
            _audit(
                uow,
                entity_type,
                proposed_name,
                decision,
                result,
                decided_by=decided_by,
                at=now,
                note=note,
                review_ids=review_ids,
            )
            return result


def _audit(
    uow: KnowledgeUnitOfWork,
    entity_type: EntityType,
    proposed_name: str,
    decision: MentionDecision,
    result: GroupDecision,
    *,
    decided_by: str,
    at: datetime,
    note: str,
    reject_reason: EntityRejectReason | None = None,
    review_ids: Sequence[UUID] | None = None,
) -> None:
    """The decision's ``entity_review.decided`` entry."""
    after: dict[str, object] = {
        "decision": decision.value,
        "status": result.status.value,
        "resolution": None if result.resolution is None else result.resolution.value,
        "entity_id": None if result.entity_id is None else str(result.entity_id),
        "items_closed": result.items_closed,
        "relation_targets_updated": result.relation_targets_updated,
    }
    if reject_reason is not None:
        after["reject_reason"] = reject_reason.value
    if review_ids:
        after["review_ids"] = sorted(str(review_id) for review_id in review_ids)
    uow.audit.write(
        entry(
            DECIDED_ACTION,
            SUBJECT,
            group_key(entity_type, proposed_name),
            actor_for(decided_by),
            at=at,
            before={"status": ReviewStatus.OPEN.value},
            after=after,
            reason=note,
        )
    )


def _can_name(entity_type: EntityType, name: str) -> bool:
    """Whether ``name`` can be an entity's canonical name or alias."""
    return bool(name) and (entity_type not in _PROVISIONS or "@" in name)
