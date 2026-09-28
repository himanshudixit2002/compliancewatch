"""A problem a validator or a stage found in its output: a code, a detail, and the clause it is
about when there is one. Issues lower confidence or send work to review; they never drop it."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    detail: str
    clause_ref: str | None = None
