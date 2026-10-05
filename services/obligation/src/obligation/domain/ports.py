"""What the application layer needs from other services, as protocols the infrastructure
implements."""

from typing import Protocol

from domain_kernel.ids import RuleVersionId
from obligation.domain.rule_versions import RuleVersionRead


class RuleVersionReader(Protocol):
    """Rule versions from the rulebook, in any status."""

    def read(
        self, rule_version_id: RuleVersionId, *, fresh: bool = False
    ) -> RuleVersionRead | None:
        """The version and the facts the cache keeps, or None when the rulebook has no such
        version. A reader may answer from a read it made a short while ago; ``fresh`` asks the
        rulebook again, as a rule event does, since the version's status has just moved. Raises
        ``RulebookUnavailableError`` when the rulebook cannot answer now."""
        ...
