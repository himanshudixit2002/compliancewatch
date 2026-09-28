"""Golden extraction cases as the harness reads them: the pipeline's case files plus the index
entries that have no case yet, so the report can say how much of the set is still unlabelled."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pipeline.label import GoldenCase, load_cases, read_index

DEFAULT_GOLDEN = Path("evals/golden")


@dataclass(frozen=True, slots=True)
class ExtractionSet:
    cases: Sequence[GoldenCase]
    indexed: int

    @property
    def labelled(self) -> list[GoldenCase]:
        return [case for case in self.cases if case.is_labelled]

    @property
    def unlabelled(self) -> int:
        return self.indexed - len(self.labelled)

    def by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.labelled:
            counts[case.label_status] = counts.get(case.label_status, 0) + 1
        return counts


def load_extraction_set(golden: Path = DEFAULT_GOLDEN) -> ExtractionSet:
    root = golden / "extraction"
    cases = load_cases(root)
    indexed = sum(len(read_index(path)["documents"]) for path in sorted(root.rglob("index.yaml")))
    return ExtractionSet(cases, max(indexed, len(cases)))
