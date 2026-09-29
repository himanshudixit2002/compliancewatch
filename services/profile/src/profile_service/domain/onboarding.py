"""The onboarding checklist of a business: every question it still has to answer, in order.

A business is a legal entity with its registrations. ``build_checklist`` lists one item per
attribute the ontology asks at each node's level: the entity first, then the registrations in
the order they were created, and the ontology's order within a node. A derived attribute is
computed rather than asked, so it has no item. A per-financial-year attribute is looked up for
the year given. ``next`` is the first item that is missing or unsure, the question onboarding
asks now, one at a time as ``ProfileNode.next_question`` does for a single node.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from domain_kernel._validation import require_instance
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId
from domain_kernel.ontology import AttributeLevel, AttributeSource, Ontology
from profile_service.domain.errors import InvalidHierarchyError
from profile_service.domain.model import ProfileNode, ValueState


class ItemState(StrEnum):
    """Where one question stands: no value yet, an unsure answer, or an answer."""

    MISSING = "missing"
    UNSURE = "unsure"
    KNOWN = "known"
    NOT_APPLICABLE = "not_applicable"


ANSWERED = frozenset({ItemState.KNOWN, ItemState.NOT_APPLICABLE})


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    node_id: BusinessId
    level: AttributeLevel
    key: str
    state: ItemState
    per_financial_year: bool
    source: AttributeSource | None
    """Where the stored answer came from; None while the attribute is missing."""

    @property
    def answered(self) -> bool:
        return self.state in ANSWERED


@dataclass(frozen=True, slots=True)
class Checklist:
    as_of_fy: FinancialYear
    items: tuple[ChecklistItem, ...]

    @property
    def next(self) -> ChecklistItem | None:
        """The first question without an answer, or None when the business is complete."""
        return next((item for item in self.items if not item.answered), None)

    @property
    def answered(self) -> int:
        return sum(1 for item in self.items if item.answered)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def complete(self) -> bool:
        return self.answered == self.total


def build_checklist(
    entity: ProfileNode,
    registrations: Sequence[ProfileNode],
    ontology: Ontology,
    fy: FinancialYear,
) -> Checklist:
    """The checklist of ``entity`` and its ``registrations`` for the financial year ``fy``."""
    require_instance(fy, FinancialYear, "fy")
    if entity.level is not AttributeLevel.ENTITY:
        raise InvalidHierarchyError("a checklist starts at the legal entity")
    for registration in registrations:
        if registration.level is not AttributeLevel.REGISTRATION or (
            registration.parent_id != entity.id
        ):
            raise InvalidHierarchyError(
                f"node {registration.id} is not a registration of entity {entity.id}"
            )
    ordered = sorted(registrations, key=lambda node: (node.created_at, node.id.value))
    items: list[ChecklistItem] = []
    for node in (entity, *ordered):
        for definition in ontology:
            if definition.level is not node.level or definition.source is AttributeSource.DERIVED:
                continue
            record = node.value(definition.key, fy if definition.per_financial_year else None)
            items.append(
                ChecklistItem(
                    node_id=node.id,
                    level=node.level,
                    key=definition.key,
                    state=ItemState.MISSING if record is None else _STATES[record.state],
                    per_financial_year=definition.per_financial_year,
                    source=None if record is None else record.source,
                )
            )
    return Checklist(as_of_fy=fy, items=tuple(items))


_STATES = {
    ValueState.KNOWN: ItemState.KNOWN,
    ValueState.UNSURE: ItemState.UNSURE,
    ValueState.NOT_APPLICABLE: ItemState.NOT_APPLICABLE,
}
