"""A pointer from a rule to the clause it came from."""

from dataclasses import dataclass

from domain_kernel._validation import require_bool, require_instance, require_text
from domain_kernel.ids import ClauseId


@dataclass(frozen=True, slots=True)
class Citation:
    """Clause reference plus the quoted text. The extractor marks it verified after checking
    the quote against the source; the kernel only records the flag."""

    clause_ref: str
    quote: str
    verified: bool = False
    clause_id: ClauseId | None = None

    def __post_init__(self) -> None:
        require_text(self.clause_ref, "clause_ref")
        require_text(self.quote, "quote", strip=False)
        require_bool(self.verified, "verified")
        if self.clause_id is not None:
            require_instance(self.clause_id, ClauseId, "clause_id")
