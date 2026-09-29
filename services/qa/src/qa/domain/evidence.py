"""The evidence an answer may use: labelled clauses it can cite and facts it can reason from.

Clauses are labelled ``C1``, ``C2`` and so on, because clause refs repeat across documents
(every notification has an ``en.p1``); the answer cites a label and the response maps it back
to the clause ref and document. Facts (``F1``, ``F2``) are what the solver worked out: a rule in
force, a relation, a decision, a due date, a comparison. They support the reasoning but cannot
be cited. The bundle is capped so that one prompt stays small.
"""

from dataclasses import dataclass, field
from typing import Final

from domain_kernel.ids import ClauseId, DocumentId

MAX_CLAUSES: Final = 12
MAX_FACTS: Final = 40
MAX_RENDERED_CHARS: Final = 2_000
"""Clause text beyond this is cut when the bundle is rendered for a prompt."""


@dataclass(frozen=True, slots=True)
class EvidenceClause:
    label: str
    clause_id: ClauseId
    document_id: DocumentId
    clause_ref: str
    text: str
    step_id: str
    source: str = ""
    """The document's number or title, shown next to the clause."""


@dataclass(frozen=True, slots=True)
class Fact:
    label: str
    step_id: str
    text: str


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    clauses: tuple[EvidenceClause, ...] = ()
    facts: tuple[Fact, ...] = ()
    dropped_clauses: int = 0
    dropped_facts: int = 0

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(clause.label for clause in self.clauses)

    @property
    def empty(self) -> bool:
        """No clause to cite: facts alone cannot back an answer."""
        return not self.clauses

    def clause(self, label: str) -> EvidenceClause | None:
        return next((clause for clause in self.clauses if clause.label == label), None)


@dataclass(slots=True)
class BundleBuilder:
    """Collects clauses once each, in the order they were first touched, and facts in order;
    what does not fit is counted, not kept."""

    _clauses: list[EvidenceClause] = field(default_factory=list)
    _facts: list[Fact] = field(default_factory=list)
    _dropped_clauses: int = 0
    _dropped_facts: int = 0

    def add_clause(
        self,
        *,
        clause_id: ClauseId,
        document_id: DocumentId,
        clause_ref: str,
        text: str,
        step_id: str,
        source: str = "",
    ) -> str | None:
        """The clause's label, the one it already has if it was added before; ``None`` when
        the bundle is full."""
        for clause in self._clauses:
            if clause.clause_id == clause_id:
                return clause.label
        if len(self._clauses) == MAX_CLAUSES:
            self._dropped_clauses += 1
            return None
        label = f"C{len(self._clauses) + 1}"
        self._clauses.append(
            EvidenceClause(label, clause_id, document_id, clause_ref, text, step_id, source)
        )
        return label

    def add_fact(self, step_id: str, text: str) -> str | None:
        if len(self._facts) == MAX_FACTS:
            self._dropped_facts += 1
            return None
        label = f"F{len(self._facts) + 1}"
        self._facts.append(Fact(label, step_id, text))
        return label

    def build(self) -> EvidenceBundle:
        return EvidenceBundle(
            tuple(self._clauses), tuple(self._facts), self._dropped_clauses, self._dropped_facts
        )


def render_bundle(bundle: EvidenceBundle) -> str:
    """The bundle as the answer prompt reads it: ``[C1] ref (document)`` then the text, then
    one line per fact."""
    lines = ["Clauses:"]
    for clause in bundle.clauses:
        heading = f"[{clause.label}] {clause.clause_ref}"
        if clause.source:
            heading += f" ({clause.source})"
        text = clause.text
        if len(text) > MAX_RENDERED_CHARS:
            text = text[:MAX_RENDERED_CHARS] + " [cut]"
        lines.extend([heading, text, ""])
    if bundle.facts:
        lines.append("Facts:")
        lines.extend(f"{fact.label}: {fact.text}" for fact in bundle.facts)
    return "\n".join(lines).rstrip()
