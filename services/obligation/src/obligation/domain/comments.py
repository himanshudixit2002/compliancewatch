"""What people say about an obligation: comments, each kept with its author, never changed.

A comment belongs to one obligation of one tenant. Its author is the user a verified access
token named (``author_id``), or nobody when no token named the caller; ``author_label`` is how
the audit log labels that actor (the user's roles, ``service:<client>`` or ``system:<service>``),
never a person's name. The body is the text as the person wrote it, trimmed, of one to
``MAX_COMMENT_CHARS`` characters. The table refuses UPDATE always and DELETE outside a tenant's
erasure, so a comment, once added, stays as it was.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import EntityId, ObligationId, TenantId, UserId

MAX_COMMENT_CHARS: Final = 2_000
MAX_AUTHOR_LABEL_CHARS: Final = 200


@dataclass(frozen=True, slots=True)
class CommentId(EntityId):
    """One comment on an obligation."""


@dataclass(frozen=True, slots=True)
class ObligationComment:
    id: CommentId
    tenant_id: TenantId
    obligation_id: ObligationId
    author_id: UserId | None
    author_label: str
    body: str
    created_at: datetime

    def __post_init__(self) -> None:
        require_instance(self.id, CommentId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        if self.author_id is not None:
            require_instance(self.author_id, UserId, "author_id")
        _bounded(
            require_text(self.author_label, "author_label"), MAX_AUTHOR_LABEL_CHARS, "author_label"
        )
        _bounded(require_text(self.body, "body"), MAX_COMMENT_CHARS, "body")
        require_aware(self.created_at, "created_at")


def _bounded(text: str, limit: int, name: str) -> str:
    if len(text) > limit:
        raise InvariantViolationError(f"{name} has at most {limit} characters, got {len(text)}")
    return text
