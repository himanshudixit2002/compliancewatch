"""One question and the reads more than one layer needs, each made once per question.

The rule versions a question may see are exactly the ones the rulebook lists as in force on
its date (``GET /rule-versions?as_of``): the structured layer, the planner's closed rule keys
and the solver all read the same set, so a draft, a version under review or a withdrawn one
never reaches an answer.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.profiles import ProfileSnapshot
from qa.domain.answer import Layer
from qa.domain.errors import BusinessNotFoundError, QuestionInvalidError
from qa.domain.ports import ProfileReader, RulebookReader
from qa.domain.records import RuleVersion

MAX_QUESTION_CHARS: Final = 1_000


@dataclass(frozen=True, slots=True)
class AskRequest:
    """``question_id`` tags every model call of the question (the request's ``x-request-id``);
    ``business`` is the profile node the question is about, which is also the business the
    obligations are kept for; ``fy`` defaults to the financial year of ``as_of``."""

    tenant: TenantId
    question: str
    as_of: date
    question_id: str
    business: BusinessId | None = None
    fy: FinancialYear | None = None

    def __post_init__(self) -> None:
        question = " ".join(self.question.split())
        if not question:
            raise QuestionInvalidError("the question is empty")
        if len(question) > MAX_QUESTION_CHARS:
            raise QuestionInvalidError(f"a question has at most {MAX_QUESTION_CHARS} characters")
        if not self.question_id.strip():
            raise QuestionInvalidError("a question needs an id")
        object.__setattr__(self, "question", question)

    @property
    def financial_year(self) -> FinancialYear:
        return self.fy or FinancialYear.for_date(self.as_of)


class AskContext:
    def __init__(
        self, request: AskRequest, rulebook: RulebookReader, profiles: ProfileReader
    ) -> None:
        self.request = request
        self._rulebook = rulebook
        self._profiles = profiles
        self._visible: dict[date, Mapping[RuleVersionId, RuleVersion]] = {}
        self._profile: ProfileSnapshot | None = None

    def visible(self, as_of: date | None = None) -> Mapping[RuleVersionId, RuleVersion]:
        """The rule versions in force on ``as_of`` (the question's date by default), by id."""
        day = as_of or self.request.as_of
        if day not in self._visible:
            versions = self._rulebook.rules_in_force(day)
            self._visible[day] = {version.rule_version_id: version for version in versions}
        return self._visible[day]

    def profile(self) -> ProfileSnapshot:
        """The business's attributes for the question's financial year."""
        if self._profile is None:
            request = self.request
            if request.business is None:
                raise QuestionInvalidError("the question names no business")
            snapshot = self._profiles.snapshot(
                request.tenant, request.business, request.financial_year
            )
            if snapshot is None:
                raise BusinessNotFoundError(str(request.business))
            self._profile = snapshot
        return self._profile

    def metadata(self, stage: str, attempt: int, layer: Layer) -> dict[str, str]:
        """The tags every model call of the question carries."""
        return {
            "question_id": self.request.question_id,
            "stage": stage,
            "attempt": str(attempt),
            "layer": layer.value,
        }
