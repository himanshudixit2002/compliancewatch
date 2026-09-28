"""The shape every pipeline stage has: validate the input, do the work, check the output.

A stage is pure and synchronous: it reads what it is given and returns what it made, with the
issues it found. Reading from and writing to other services is the activity's job
(``py_common.temporal.ActivityBase``), which calls ``execute`` in between. So a stage runs the
same in a unit test, in the labelling tool and inside a Temporal activity.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from pipeline.domain.issues import Issue


class StageInputError(ValueError):
    """The stage was called with an input it cannot work on: a bug in the caller, not a
    property of the document."""


@dataclass(frozen=True, slots=True)
class StageOutcome[T]:
    """What a stage made, what it found wrong with it, and whether a person should look."""

    output: T
    issues: tuple[Issue, ...] = ()
    needs_review: bool = False


class PipelineStage[In, Out](ABC):
    """Template method: ``execute`` runs ``validate``, ``process`` and ``check`` in that order.
    ``name`` and ``version`` identify the stage in what it stores (``grammar@1``)."""

    name: ClassVar[str]
    version: ClassVar[str]

    def execute(self, input: In) -> StageOutcome[Out]:
        self.validate(input)
        output = self.process(input)
        issues = tuple(self.check(input, output))
        return StageOutcome(output, issues, needs_review=self.needs_review(output, issues))

    def validate(self, input: In) -> None:  # noqa: B027 (optional hook)
        """Raise ``StageInputError`` for an input the stage cannot work on."""

    @abstractmethod
    def process(self, input: In) -> Out:
        """The work."""

    def check(self, input: In, output: Out) -> Iterable[Issue]:
        """Issues with the output; the default finds none."""
        return ()

    def needs_review(self, output: Out, issues: tuple[Issue, ...]) -> bool:
        """Whether a person should look; the default is any issue at all."""
        return bool(issues)
