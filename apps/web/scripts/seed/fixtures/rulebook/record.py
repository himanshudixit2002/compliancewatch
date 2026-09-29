"""Records the rulebook fixtures the web seed replays for notification 01/2026-Central Tax.

Run from the repository root (the demo package depends on the pipeline and the rulebook):

    uv run --package compliancewatch-demo python apps/web/scripts/seed/fixtures/rulebook/record.py
    pnpm exec prettier --write apps/web/scripts/seed/fixtures/rulebook

The script parses the recorded PDF
(``services/pipeline/tests/fixtures/cbic/gst-ct-01-2026.pdf.json``) with the pipeline's
``PdfParser``, runs the mention grammar and the relation stage over the parsed document the way
``pipeline.application.knowledge_activities`` does, and captures the request bodies the
pipeline's ``HttpRulebook`` sends to an in-process rulebook on the memory store. The seed then
sends the same bodies to a running rulebook. The title and the publication date are the source
listing's (``notifications-2026-p0.json`` in the same fixture directory), which is what
``RegisterDocument`` stores when the CBIC source is fetched; the relation candidate is the
scripted model answer the demo's knowledge-flow test stages
(``tools/demo/tests/unit/test_knowledge_flow.py``), not a model call, and its ``model`` field
says so.
"""

import base64
import dataclasses
import json
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from domain_kernel.documents import DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from pipeline.application.detector import detect
from pipeline.application.mentions import MentionInput, MentionStage
from pipeline.application.relations import LlmRelationExtractor, RelationInput, RelationStage
from pipeline.domain.grammar import mentions_for
from pipeline.domain.knowledge import DocumentRecord, MentionSubmission, RelationSubmission
from pipeline.infrastructure.parsers import PdfParser
from pipeline.infrastructure.prompts import load_prompt
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.testing import ScriptedProvider
from rulebook.main import build_app
from rulebook.testing import WRITE_TOKEN, rulebook_settings

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
NAME = "gst-ct-01-2026"
PDF_WRAPPER = ROOT / "services" / "pipeline" / "tests" / "fixtures" / "cbic" / f"{NAME}.pdf.json"

SOURCE_ID = SourceId(UUID("00000000-0000-4000-8000-00000000000b"))
"""A fixed id for the seed's source row; the pipeline's source registry does not exist yet."""
CBIC_PDF_BASE = "https://taxinformation.cbic.gov.in/content/pdf/tax_repository/gst/notifications"
URL = f"{CBIC_PDF_BASE}/{NAME}.pdf"
EXTERNAL_REF = "01/2026-Central Tax"
TITLE = (
    "Seeks to extends the due date for furnishing the return in FORM GSTR-3B for the month of "
    "March, 2026 till the twenty-first day of April, 2026"
)
PUBLISHED_AT = date(2026, 4, 21)
FETCHED_AT = datetime(2026, 9, 28, tzinfo=UTC)
REGULATOR = "CBIC"
MONTHLY_RULE = "gstr3b_monthly"
"""Known to the in-process rulebook while recording, so the candidate carries the rule key; the
seed blanks it when the target rulebook does not list the rule."""

SCRIPTED_ANSWER = json.dumps(
    {
        "relations": [
            {
                "relation": "extends_deadline",
                "target_mention": "M2",
                "rule_key": MONTHLY_RULE,
                "evidence_clause_ref": "en.p3",
                "evidence_quote": (
                    "hereby extends the due  date for furnishing the return in FORM GSTR-3B for "
                    "the month of March, 2026 till the twenty -first day of April, 2026"
                ),
                "period": "2026-03",
                "new_due_date": "2026-04-21",
                "confidence": 0.9,
            }
        ]
    }
)

FILE_FOR_PATH = {"mentions": "mentions", "relation-candidates": "relations"}


class RecordingRulebook(HttpRulebook):
    """The pipeline's client over an in-process app, keeping every PUT body it sends."""

    def __init__(self, client: TestClient) -> None:
        super().__init__(token=WRITE_TOKEN, client=client)
        self.bodies: dict[str, dict[str, Any]] = {}

    def _send(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> Any:
        if method == "put" and body is not None:
            self.bodies[FILE_FOR_PATH.get(path.rsplit("/", 1)[-1], "document")] = dict(body)
        return super()._send(method, path, body, params=params)


def main() -> int:
    wrapper = json.loads(PDF_WRAPPER.read_text(encoding="utf-8"))
    raw = RawDocument.from_bytes(
        DocumentRef(SOURCE_ID, URL, EXTERNAL_REF),
        base64.b64decode(wrapper["data"]),
        "application/pdf",
        FETCHED_AT,
    )
    parsed = dataclasses.replace(PdfParser().parse(raw), title=TITLE, published_at=PUBLISHED_AT)
    record = DocumentRecord(
        document=parsed,
        source_id=SOURCE_ID,
        sha256=raw.sha256,
        regulator=REGULATOR,
        url=URL,
        media_type=raw.media_type,
        fetched_at=FETCHED_AT,
        external_ref=EXTERNAL_REF,
    )
    app = build_app(rulebook_settings())
    with TestClient(app) as client:
        app.state.wiring.unit_of_work.add_rule(MONTHLY_RULE, title="GSTR-3B monthly return")
        rulebook = RecordingRulebook(client)
        registered = rulebook.register_document(record)
        if registered.document_id != parsed.document_id:
            raise SystemExit("the rulebook derived another document id than the kernel")
        mentions = MentionStage().execute(MentionInput(parsed, own_ref=EXTERNAL_REF)).output
        alignment = rulebook.submit_mentions(
            MentionSubmission(parsed.document_id, MentionStage.version, mentions)
        )
        detection = detect(parsed, own_ref=EXTERNAL_REF)
        stage = RelationStage(
            LlmRelationExtractor(
                ScriptedProvider({}, default=SCRIPTED_ANSWER),
                load_prompt("extraction.rule_relations", "1"),
            )
        )
        batch = stage.execute(
            RelationInput(
                document=parsed,
                mentions=mentions_for(parsed, own_ref=EXTERNAL_REF),
                rules=rulebook.known_rules(),
                change_kind=detection.change_kind,
                own_ref=EXTERNAL_REF,
                regulator=REGULATOR,
            )
        ).output
        staging = rulebook.submit_relations(
            RelationSubmission(
                document_id=parsed.document_id,
                extractor=RelationStage.version,
                model=batch.model,
                outcome=batch.outcome,
                candidates=batch.candidates,
                run_issues=batch.run_issues,
            )
        )
    for key in ("document", "mentions", "relations"):
        target = HERE / f"{NAME}.{key}.json"
        target.write_text(
            json.dumps(rulebook.bodies[key], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        sys.stderr.write(f"wrote {target.relative_to(ROOT)}\n")
    sys.stderr.write(
        f"document {parsed.document_id} ({len(parsed.clauses)} clauses, sha256 {raw.sha256});"
        f" {len(mentions)} mentions ({alignment.queued} queued);"
        f" {len(batch.candidates)} relation candidate(s) ({staging.created} created)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
