"""The synthetic analysts of the local product's demo publication: fixed ids and names that no
person holds.

``cw-product publish`` submits each seed rule ``evals/golden/qa/kag/world.yaml`` cites from a
recorded quote as ``DRAFTER``, tags it high impact so that two different approvers must approve
it, approves it as ``FIRST_REVIEWER`` and then ``SECOND_REVIEWER``, and publishes it as the first.
Every note those steps carry is ``NOTE``. None of them is an analyst review: each approval is
marked synthetic, so the rulebook leaves the version's seed status at needs_review, and it
accepts such approvals only where ``CW_ENV`` is local or test.
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SyntheticAnalyst:
    user_id: UUID
    name: str


DRAFTER: Final = SyntheticAnalyst(
    UUID("00000000-0000-4000-8000-00000000a001"), "Demo analyst (synthetic)"
)
FIRST_REVIEWER: Final = SyntheticAnalyst(
    UUID("00000000-0000-4000-8000-00000000a002"), "Demo reviewer one (synthetic)"
)
SECOND_REVIEWER: Final = SyntheticAnalyst(
    UUID("00000000-0000-4000-8000-00000000a003"), "Demo reviewer two (synthetic)"
)
REVIEWERS: Final = (FIRST_REVIEWER, SECOND_REVIEWER)
"""Two different approvers, as a high-impact version needs (ADR-006)."""
ANALYSTS: Final = (DRAFTER, *REVIEWERS)
NOTE: Final = "synthetic demo publication - not an analyst review"
"""The note of every step of the demo publication."""
