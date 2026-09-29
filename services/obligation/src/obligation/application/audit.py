"""Publish an obligation event and write its change log row in the same unit of work.

Every use case that changes an obligation calls ``record`` where it used to publish the event
alone, so the outbox row and the change row commit or roll back together (ADR-015: every change
writes an audit row). A use case that leaves an obligation as it was, or skips a closed one,
publishes nothing and so records nothing.
"""

from obligation.domain.history import ObligationEvent, change_from_event
from obligation.domain.model import Obligation
from obligation.domain.repository import UnitOfWork


def record(uow: UnitOfWork, event: ObligationEvent, after: Obligation) -> None:
    """Publish ``event`` and append the change it made; ``after`` is the changed obligation."""
    change = change_from_event(event, after)
    uow.events.publish(event)
    uow.history.append(change)
