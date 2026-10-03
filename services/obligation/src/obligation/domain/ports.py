"""What the application layer needs from other services, as protocols the infrastructure
implements."""

from typing import Protocol

from domain_kernel.ids import RuleVersionId
from domain_kernel.rules import RuleVersionSnapshot


class RuleVersionReader(Protocol):
    """Rule versions from the rulebook, in any status."""

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionSnapshot | None:
        """The version, or None when the rulebook has no such version. Raises
        ``RulebookUnavailableError`` when the rulebook cannot answer now."""
        ...
