"""Run the rulebook data-quality checks over what a reader returns.

The reader is a port: it returns plain facts (versions with their citation counts, and the
edges between rule versions) and never writes. The Postgres reader runs its queries in a
read-only transaction, so the checks can point at a deployed database through a read-only role.
"""

from typing import Protocol

from domain_kernel.ontology import Ontology
from rulebook.domain.quality import QualityFacts, QualityReport, run_checks


class QualityReader(Protocol):
    def read(self) -> QualityFacts:
        """Every rule version with its citation counts, and every edge between rule versions."""
        ...


class RunDataQualityChecks:
    def __init__(self, reader: QualityReader, ontology: Ontology) -> None:
        self._reader = reader
        self._ontology = ontology

    def run(self) -> QualityReport:
        return run_checks(self._reader.read(), self._ontology)
