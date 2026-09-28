"""The knowledge flow over a recorded notification, pipeline and rulebook in one process.

The pipeline's activities talk to the rulebook app through its HTTP client, the model is a
scripted answer, and the analyst's steps go through the review API: the mentions of 01/2026 are
aligned or queued, the model's extension of GSTR-3B is staged, the analyst creates the entity
for the form, and approving the candidate writes a rule relation from a draft version to the
version it extends.
"""

import base64
import dataclasses
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.documents import DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from domain_kernel.status import RuleVersionStatus
from pipeline.application.knowledge_activities import (
    ExtractMentions,
    MentionsRequest,
    ProposeRelations,
    RelationsRequest,
    SubmitRelations,
)
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.domain.knowledge import DocumentRecord
from pipeline.infrastructure.parsers import PdfParser
from pipeline.infrastructure.prompts import load_prompt
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.testing import ScriptedProvider
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app
from rulebook.testing import WRITE_TOKEN, rulebook_settings

FIXTURES = Path(__file__).resolve().parents[4] / "services" / "pipeline" / "tests" / "fixtures"
BASE = "/v1/rulebook"
AUTH = {"x-cw-write-token": WRITE_TOKEN}
MONTHLY = "gstr3b_monthly"
ANSWER = json.dumps(
    {
        "relations": [
            {
                "relation": "extends_deadline",
                "target_mention": "M2",
                "rule_key": MONTHLY,
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


@pytest.fixture
def app() -> FastAPI:
    return build_app(rulebook_settings())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def recorded() -> DocumentRecord:
    name = "gst-ct-01-2026.pdf"
    wrapper = json.loads((FIXTURES / "cbic" / f"{name}.json").read_text(encoding="utf-8"))
    source = SourceId(UUID(int=11))
    ref = DocumentRef(source, f"https://example.invalid/{name}", "01/2026-Central Tax")
    raw = RawDocument.from_bytes(
        ref, base64.b64decode(wrapper["data"]), "application/pdf", datetime(2026, 9, 28, tzinfo=UTC)
    )
    return DocumentRecord(
        document=PdfParser().parse(raw),
        source_id=source,
        sha256=raw.sha256,
        regulator="CBIC",
        url=ref.url,
        media_type=raw.media_type,
        fetched_at=raw.fetched_at,
        external_ref=ref.external_ref,
    )


async def test_mentions_relations_review_and_approval(app: FastAPI, client: TestClient) -> None:
    store: MemoryKnowledgeStore = app.state.wiring.unit_of_work
    store.add_rule(MONTHLY, title="GSTR-3B monthly return")
    _, extension = store.add_rule("gstr3b_extension_2026_03")
    _, monthly = store.add_rule("gstr3b_monthly_v1", status=RuleVersionStatus.PUBLISHED)
    rulebook = HttpRulebook(token=WRITE_TOKEN, client=client)
    record = recorded()
    rulebook.register_document(record)
    document_id = record.document.document_id.value

    mentions = await ExtractMentions(rulebook, rulebook, enabled=True).run(
        MentionsRequest(document_id=document_id, own_ref="01/2026-Central Tax")
    )
    assert (mentions.found, mentions.aligned, mentions.queued) == (5, 0, 5)
    groups = client.get(f"{BASE}/review/entities").json()
    assert [(g["entity_type"], g["proposed_name"]) for g in groups] == [
        ("form", "GSTR-3B"),
        ("notification", "01/2026-central tax"),
        ("rule", "61(1)(i)@cgst-rules"),
        ("section", "39(1)@cgst-act"),
        ("section", "39(6)@cgst-act"),
    ]

    stage = RelationStage(
        LlmRelationExtractor(
            ScriptedProvider({}, default=ANSWER), load_prompt("extraction.rule_relations", "1")
        )
    )
    batch = await ProposeRelations(rulebook, stage, enabled=True).run(
        RelationsRequest(document_id=document_id, own_ref="01/2026-Central Tax", regulator="CBIC")
    )
    assert (batch.outcome, len(batch.candidates)) == ("ok", 1)
    staged = await SubmitRelations(rulebook, enabled=True).run(batch)
    assert staged.created == 1

    decided = client.post(
        f"{BASE}/review/entities/decisions",
        json={
            "entity_type": "form",
            "proposed_name": "GSTR-3B",
            "decision": "create_entity",
            "decided_by": "analyst",
        },
        headers=AUTH,
    ).json()
    assert decided["relation_targets_updated"] == 1
    (candidate,) = client.get(f"{BASE}/review/relations").json()
    assert candidate["target_entity_id"] == decided["entity_id"]
    assert (candidate["target_rule_key"], candidate["new_due_on"]) == (MONTHLY, "2026-04-21")
    approval = client.post(
        f"{BASE}/review/relations/{candidate['candidate_id']}/approve",
        json={
            "from_rule_version_id": str(extension),
            "target_rule_version_id": str(monthly),
            "decided_by": "analyst",
        },
        headers=AUTH,
    )
    assert approval.status_code == 200
    ((relation, candidate_id),) = store.rule_relations()
    assert str(candidate_id) == candidate["candidate_id"]
    assert (relation.from_rule_version_id, relation.target) == (extension, monthly)

    again = await ExtractMentions(rulebook, rulebook, enabled=True).run(
        MentionsRequest(document_id=document_id, own_ref="01/2026-Central Tax")
    )
    assert again.aligned == 0
    assert again.unchanged == 5


async def test_the_reader_gives_back_the_parsed_document(client: TestClient) -> None:
    rulebook = HttpRulebook(token=WRITE_TOKEN, client=client)
    record = recorded()
    rulebook.register_document(record)
    document = rulebook.parsed_document(record.document.document_id)
    assert document == dataclasses.replace(record.document, title=record.document.title)
    assert rulebook.known_rules() == ()
