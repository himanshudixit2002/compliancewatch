"""Backfill a source: list, fetch, store and parse every document since a date.

``pipeline-backfill --source cbic_notifications --since 2025-01-01 --store ./var/raw``
prints one line per document: the source key, the published date, the digest, the document
type the detector settled on, the change kind and the references it found, then a summary.
``--limit`` caps the documents per run for a first look; ``--list-only`` skips the fetch.
The same steps run inside the ingest workflow; this command is for operators and for recording
fixtures.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from domain_kernel.documents import DiscoveredDocument, DocumentType, ParsedDocument, RawDocument
from domain_kernel.protocols import DocumentParser, SourceAdapter
from pipeline.application.detector import Detection, detect
from pipeline.domain.ports import RawStore
from pipeline.infrastructure.adapters import SOURCES, build_adapter
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.parsers import HtmlParser, PdfParser
from pipeline.infrastructure.parsers.pdf import UnparsedDocumentError
from pipeline.infrastructure.raw_store import LocalRawStore


@dataclass(frozen=True, slots=True)
class BackfillResult:
    listed: int
    fetched: int
    parsed: int
    unparsed: int
    failed: int


@dataclass(frozen=True, slots=True)
class Ingested:
    discovered: DiscoveredDocument
    raw: RawDocument
    uri: str
    parsed: ParsedDocument | None
    detection: Detection | None


def parsers_for(doc_type: DocumentType) -> list[DocumentParser]:
    return [PdfParser(doc_type=doc_type), HtmlParser(doc_type=doc_type)]


def ingest(
    adapter: SourceAdapter,
    parsers: Sequence[DocumentParser],
    store: RawStore,
    *,
    source_key: str,
    since: datetime,
    default_type: DocumentType,
    limit: int | None = None,
    list_only: bool = False,
    out: list[str] | None = None,
) -> BackfillResult:
    listed = fetched = parsed_count = unparsed = failed = 0
    for discovered in adapter.list_documents(since):
        if limit is not None and listed >= limit:
            break
        listed += 1
        if list_only:
            _emit(out, f"{source_key}\t{discovered.published_at}\t-\t{discovered.title[:80]}")
            continue
        try:
            raw = adapter.fetch(discovered.ref)
        except Exception as exc:
            failed += 1
            _emit(out, f"{source_key}\t{discovered.published_at}\tfetch failed\t{exc}")
            continue
        fetched += 1
        uri = store.uri(store.put(raw))
        parser = next((p for p in parsers if p.supports(raw)), None)
        try:
            if parser is None:
                raise UnparsedDocumentError(f"no parser for {raw.media_type}")
            parsed = parser.parse(raw)
        except UnparsedDocumentError as exc:
            unparsed += 1
            _emit(
                out, f"{source_key}\t{discovered.published_at}\t{raw.sha256[:12]}\tunparsed\t{exc}"
            )
            continue
        parsed_count += 1
        detection = detect(parsed, default_type=default_type, own_ref=discovered.ref.external_ref)
        refs = ",".join(detection.references) or "-"
        _emit(
            out,
            f"{source_key}\t{discovered.published_at}\t{raw.sha256[:12]}\t{detection.doc_type.value}"
            f"\t{detection.change_kind.value}\t{refs}\t{uri}",
        )
    return BackfillResult(listed, fetched, parsed_count, unparsed, failed)


def _emit(out: list[str] | None, line: str) -> None:
    if out is None:
        sys.stdout.write(line + "\n")
    else:
        out.append(line)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline-backfill", description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--since", type=date.fromisoformat, default=date(date.today().year, 1, 1))
    parser.add_argument("--store", type=Path, default=Path("var/raw"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--delay", type=float, default=ClientConfig().min_delay_seconds)
    args = parser.parse_args(argv)
    spec = SOURCES[args.source]
    since = datetime.combine(args.since, datetime.min.time(), tzinfo=UTC)
    with PoliteClient(ClientConfig(min_delay_seconds=args.delay)) as client:
        adapter = build_adapter(args.source, client)
        result = ingest(
            adapter,
            parsers_for(spec.doc_type),
            LocalRawStore(args.store),
            source_key=args.source,
            since=since,
            default_type=spec.doc_type,
            limit=args.limit,
            list_only=args.list_only,
        )
    sys.stdout.write(
        f"{args.source}: listed {result.listed}, fetched {result.fetched}, parsed {result.parsed}, "
        f"unparsed {result.unparsed}, failed {result.failed}\n"
    )
    return 1 if result.failed and not result.fetched else 0


if __name__ == "__main__":
    raise SystemExit(main())
