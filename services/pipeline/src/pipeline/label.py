"""The labelling tool: golden extraction cases for analysts to fill in and the harness to score.

``pipeline-label index`` lists the documents a source published since a date into an index
file, each with ``label_status: draft``. ``pipeline-label prepare`` fetches and parses the
documents in an index and writes one case file per document: the clauses as the analyst reads
them, and an ``expected`` block prefilled by the deterministic detector (document kind, change
kind, references) with every model-dependent field left empty for a person. ``pipeline-label
check`` reads every case, makes sure the expected block is a valid candidate that cites clauses
in its own document and passes the validators, and reports how many cases are draft, reviewed
and approved. Nothing here calls a model.
"""

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from domain_kernel.documents import (
    Clause,
    DiscoveredDocument,
    DocumentRef,
    DocumentType,
    ParsedDocument,
    RawDocument,
    document_id_for,
)
from domain_kernel.protocols import DocumentParser, SourceAdapter
from ontology import load as load_ontology
from pipeline.application.detector import detect
from pipeline.application.validators import validate
from pipeline.domain.candidate import CandidateParseError, candidate_from_mapping
from pipeline.infrastructure.adapters import SOURCES, build_adapter
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.parsers import HtmlParser, PdfParser
from pipeline.infrastructure.parsers.pdf import UnparsedDocumentError

LABEL_STATUSES = ("draft", "reviewed", "approved")
_SLUG = re.compile(r"[^a-z0-9]+")


class LabelError(ValueError):
    """A case file is not usable as a golden case."""


@dataclass(frozen=True, slots=True)
class GoldenCase:
    case_id: str
    label_status: str
    source: Mapping[str, Any]
    document: ParsedDocument
    expected: Mapping[str, Any] | None
    path: Path

    @property
    def is_labelled(self) -> bool:
        return self.expected is not None


def slug(text: str) -> str:
    return _SLUG.sub("-", text.casefold()).strip("-")


def write_index(
    adapter: SourceAdapter, *, source_key: str, since: datetime, limit: int, path: Path
) -> int:
    entries: list[dict[str, object]] = []
    for discovered in adapter.list_documents(since):
        if len(entries) >= limit:
            break
        entries.append(
            {
                "number": discovered.ref.external_ref,
                "title": discovered.title,
                "url": discovered.ref.url,
                "published_at": None
                if discovered.published_at is None
                else discovered.published_at.isoformat(),
                "label_status": "draft",
                "case": None,
            }
        )
    index = {
        "source_key": source_key,
        "listed_on": date.today().isoformat(),
        "since": since.date().isoformat(),
        "documents": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(index, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )
    return len(entries)


def read_index(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        raise LabelError(f"{path} is not an index: needs source_key and documents")
    return data


def prepare_case(
    raw: RawDocument,
    discovered: DiscoveredDocument,
    parsers: Sequence[DocumentParser],
    *,
    source_key: str,
    default_type: DocumentType,
    cases_dir: Path,
) -> Path:
    parser = next((p for p in parsers if p.supports(raw)), None)
    if parser is None:
        raise UnparsedDocumentError(f"no parser for {raw.media_type}")
    parsed = parser.parse(raw)
    detection = detect(parsed, default_type=default_type, own_ref=discovered.ref.external_ref)
    case_id = slug(discovered.ref.external_ref or discovered.title)
    case = {
        "case_id": case_id,
        "label_status": "draft",
        "labelled_by": "",
        "reviewed_by": "",
        "source": {
            "source_key": source_key,
            "number": discovered.ref.external_ref,
            "title": discovered.title,
            "url": discovered.ref.url,
            "published_at": None
            if discovered.published_at is None
            else discovered.published_at.isoformat(),
            "sha256": raw.sha256,
            "fetched_at": raw.fetched_at.isoformat(),
        },
        "document": {
            "doc_type": parsed.doc_type.value,
            "language": parsed.language,
            "title": parsed.title,
            "clauses": [
                {"ref": c.clause_ref, "page": c.page, "text": c.text} for c in parsed.clauses
            ],
        },
        "detector": {
            "doc_kind": detection.doc_type.value,
            "change_kind": detection.change_kind.value,
            "references": list(detection.references),
        },
        "expected": None,
        "notes": "Fill in expected as a candidate (see evals/golden/extraction/README.md); "
        "set label_status to reviewed when done.",
    }
    cases_dir.mkdir(parents=True, exist_ok=True)
    path = cases_dir / f"{case_id}.yaml"
    path.write_text(
        yaml.safe_dump(case, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )
    return path


def load_case(path: Path) -> GoldenCase:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise LabelError(f"{path}: not a mapping")
    status = data.get("label_status")
    if status not in LABEL_STATUSES:
        raise LabelError(f"{path}: label_status must be one of {', '.join(LABEL_STATUSES)}")
    document = data.get("document")
    source = data.get("source")
    if not isinstance(document, dict) or not isinstance(source, dict):
        raise LabelError(f"{path}: needs document and source blocks")
    sha256 = str(source.get("sha256", ""))
    if len(sha256) != 64:
        raise LabelError(f"{path}: source.sha256 must be the document digest")
    clauses = tuple(
        Clause(clause_ref=str(c["ref"]), text=str(c["text"]), page=c.get("page"))
        for c in document.get("clauses", [])
    )
    if not clauses:
        raise LabelError(f"{path}: the document has no clauses")
    parsed = ParsedDocument(
        document_id=document_id_for(sha256),
        doc_type=DocumentType(str(document.get("doc_type", "notification"))),
        title=str(document.get("title", "")),
        clauses=clauses,
        language=str(document.get("language", "en")),
    )
    expected = data.get("expected")
    if expected is not None and not isinstance(expected, dict):
        raise LabelError(f"{path}: expected must be a mapping or null")
    return GoldenCase(
        str(data.get("case_id", path.stem)), str(status), source, parsed, expected, path
    )


def check_case(case: GoldenCase) -> list[str]:
    """Problems with a labelled case; an unlabelled one has none (it is simply not scored)."""
    if case.expected is None:
        return []
    try:
        fields = candidate_from_mapping(case.expected)
    except CandidateParseError as exc:
        return [f"{case.path.name}: expected is not a candidate: {exc}"]
    report = validate(fields, case.document, load_ontology())
    return [f"{case.path.name}: {i.code} {i.detail}" for i in report.issues]


def load_cases(root: Path) -> list[GoldenCase]:
    return [load_case(path) for path in sorted(root.rglob("cases/*.yaml"))]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline-label", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="list a source's documents into an index file")
    index.add_argument("--source", required=True, choices=sorted(SOURCES))
    index.add_argument("--since", type=date.fromisoformat, required=True)
    index.add_argument("--limit", type=int, default=50)
    index.add_argument("--out", type=Path, required=True)
    prepare = commands.add_parser("prepare", help="fetch, parse and write a case file per document")
    prepare.add_argument("--index", type=Path, required=True)
    prepare.add_argument("--number", default=None, help="only this document number")
    prepare.add_argument("--limit", type=int, default=None)
    check = commands.add_parser("check", help="validate every case under a golden directory")
    check.add_argument("--golden", type=Path, default=Path("evals/golden/extraction"))
    args = parser.parse_args(argv)
    if args.command == "index":
        since = datetime.combine(args.since, datetime.min.time(), tzinfo=UTC)
        with PoliteClient(ClientConfig()) as client:
            count = write_index(
                build_adapter(args.source, client),
                source_key=args.source,
                since=since,
                limit=args.limit,
                path=args.out,
            )
        sys.stdout.write(f"{args.out}: {count} documents, all label_status draft\n")
        return 0
    if args.command == "prepare":
        return _prepare(args.index, args.number, args.limit)
    return _check(args.golden)


def _prepare(index_path: Path, number: str | None, limit: int | None) -> int:
    index = read_index(index_path)
    spec = SOURCES[str(index["source_key"])]
    parsers: list[DocumentParser] = [
        PdfParser(doc_type=spec.doc_type),
        HtmlParser(doc_type=spec.doc_type),
    ]
    cases_dir = index_path.parent / "cases"
    done = 0
    with PoliteClient(ClientConfig()) as client:
        adapter = build_adapter(spec.key, client)
        for entry in index["documents"]:
            if entry.get("case") or (number and entry.get("number") != number):
                continue
            if limit is not None and done >= limit:
                break
            discovered = _discovered(entry, spec)
            try:
                raw = adapter.fetch(discovered.ref)
                path = prepare_case(
                    raw,
                    discovered,
                    parsers,
                    source_key=spec.key,
                    default_type=spec.doc_type,
                    cases_dir=cases_dir,
                )
            except (UnparsedDocumentError, OSError) as exc:
                sys.stdout.write(f"{entry.get('number')}: skipped ({exc})\n")
                continue
            entry["case"] = str(path.relative_to(index_path.parent))
            done += 1
            sys.stdout.write(f"{entry.get('number')}: {entry['case']}\n")
    index_path.write_text(
        yaml.safe_dump(index, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )
    sys.stdout.write(f"prepared {done} case files under {cases_dir}\n")
    return 0


def _discovered(entry: Mapping[str, Any], spec: Any) -> DiscoveredDocument:
    published = entry.get("published_at")
    return DiscoveredDocument(
        ref=DocumentRef(
            spec.source_id, str(entry["url"]), external_ref=str(entry.get("number", ""))
        ),
        title=str(entry.get("title", "")),
        published_at=None if not published else date.fromisoformat(str(published)),
    )


def _check(golden: Path) -> int:
    problems: list[str] = []
    counts = dict.fromkeys(LABEL_STATUSES, 0)
    labelled = 0
    cases = load_cases(golden)
    for case in cases:
        counts[case.label_status] += 1
        if case.is_labelled:
            labelled += 1
        problems.extend(check_case(case))
    for problem in problems:
        sys.stdout.write(f"problem: {problem}\n")
    indexed = sum(len(read_index(p)["documents"]) for p in golden.rglob("index.yaml"))
    sys.stdout.write(
        f"{golden}: {indexed} indexed, {len(cases)} case files, {labelled} labelled "
        f"({', '.join(f'{k} {v}' for k, v in counts.items())}), {len(problems)} problems\n"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
