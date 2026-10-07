"""The rulebook's audit entries: who decided what about the regulatory data, in ``audit.event``.

Every human review action writes one entry (``domain_kernel.audit``) through the ``audit`` sink
of the unit of work that makes the change, so the entry commits or rolls back with it:

- ``entity_review.decided``: a mention group decided (``review.DecideMentionGroup``). The subject
  id is the group's key, ``<entity_type>:<proposed_name>``: a group has no id of its own, and a
  rejection names no entity.
- ``relation_candidate.approved`` and ``.rejected``: the candidate id.
- ``rule_version.submitted``, ``.approved``, ``.returned``, ``.published`` and ``.withdrawn``:
  the version id, written by the step itself (``publication``), so a review task's decision that
  runs the step writes it once.
- ``review_task.claimed``, ``.drafted`` and ``.decided``: the task id. An edit of a task's draft
  writes no entry: its ``edited`` row of the decision audit records it already.

Regulatory data is global, so every entry is a platform row (``tenant_id`` None). The decision
audit (``rule_version_decision``) stays the record approvals are counted from; these entries are
the trail across services. Seeding, the pipeline's intake and reads write none.

Volume: a few rows per human review action (a review task's approval of a draft writes three:
submitted, approved and the task's decision), so the rulebook adds at most a few thousand rows a
month to the log.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Final
from uuid import UUID

from domain_kernel.audit import AuditActor, AuditActorKind, AuditEntry
from domain_kernel.ids import UserId
from py_common.audit import audit_actor, current_correlation_id

SERVICE: Final = "rulebook"


def actor_for(user: UserId | str | None) -> AuditActor:
    """Who acted: the request's verified user when it is ``user`` (with the roles they hold),
    else ``user`` as a person without roles, else the request's service client or the system.
    ``user`` may be text, as a relation or entity decision names who decided: a user id in its
    text form is that user, any other text (a service client, or a name sent without a token) is
    left to the request's principal."""
    user_id = _user_id(user)
    bound = audit_actor(SERVICE)
    if user_id is None:
        return bound
    if bound.kind is AuditActorKind.USER and bound.id == str(user_id):
        return bound
    return AuditActor.user(user_id)


def entry(
    action: str,
    subject_type: str,
    subject_id: object,
    actor: AuditActor,
    *,
    at: datetime,
    before: Mapping[str, object] | None = None,
    after: Mapping[str, object] | None = None,
    reason: str = "",
) -> AuditEntry:
    """A platform entry of the rulebook, with the request's correlation id."""
    return AuditEntry(
        action=action,
        tenant_id=None,
        subject_type=subject_type,
        subject_id=str(subject_id),
        actor=actor,
        reason=reason,
        before=before,
        after=after,
        occurred_at=at,
        correlation_id=current_correlation_id(),
    )


def _user_id(user: UserId | str | None) -> UserId | None:
    if user is None or isinstance(user, UserId):
        return user
    try:
        value = UUID(user)
    except ValueError:
        return None
    return UserId(value) if str(value) == user else None
