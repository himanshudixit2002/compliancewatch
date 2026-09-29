"""Test doubles for tests, demos and the evals: settings that ignore the repo ``.env``, the
upstream services in memory, a scripted model, a fake embedder and a tracer that keeps its
spans; ``memory_ports`` puts them together for ``build_app(ports=...)``.

``MemoryRulebook`` answers the rulebook's read API with its rules: the versions in force on a
date are the published or superseded ones whose period contains it, relations are those from
versions that have been published, a name resolves by canonical name or by the one alias of
exactly one entity, and search ranks clauses by the question words they share. A search hit or
an entity's clause is ``out_of_force`` on a date when published, superseded or withdrawn
versions cite it with a verified quote and none of them is in force then. Setting ``fail`` on a
fake makes every read raise ``DependencyUnavailableError``.
"""

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from typing import Any, Final
from uuid import UUID, uuid4

from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import (
    BusinessId,
    CanonicalEntityId,
    ClauseId,
    DocumentId,
    ObligationId,
    RuleVersionId,
    TenantId,
)
from domain_kernel.knowledge import (
    RULE_VERSION_KIND,
    EntityType,
    RelationKind,
    normalise_name,
)
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.profiles import ProfileSnapshot
from domain_kernel.status import ObligationStatus
from domain_kernel.vectors import EMBEDDING_DIMS, Vector
from qa.domain.errors import DependencyUnavailableError
from qa.domain.plan_schema import FIELDS
from qa.domain.ports import AttributeValue
from qa.domain.records import (
    INDIA,
    ClauseRecord,
    Entity,
    EntityResolution,
    ObligationRecord,
    QueryEmbedding,
    Relation,
    ResolutionStatus,
    RuleVersion,
    RuleVersionDetail,
    SearchHit,
    VersionCitation,
)
from qa.settings import QaSettings
from qa.wiring import Ports

PUBLISHED: Final = "published"
HAS_BEEN_PUBLISHED: Final = frozenset({PUBLISHED, "superseded"})
WAS_PUBLISHED: Final = HAS_BEEN_PUBLISHED | {"withdrawn"}
"""The statuses whose citations say whether a clause is out of force."""
_WORD = re.compile(r"[a-z0-9]+(?:[-/.][a-z0-9]+)*")
_STOP_WORDS: Final = frozenset(
    {"a", "an", "and", "are", "by", "for", "i", "is", "my", "of", "on", "the", "to", "what", "when"}
)


def qa_settings(**overrides: Any) -> QaSettings:
    """Settings that ignore the repo ``.env``; explicit values win over the environment. The
    KAG flag keeps its default (off) unless a test turns it on."""
    values: dict[str, Any] = {"_env_file": None, "service_name": "qa"}
    values.update(overrides)
    return QaSettings(**values)


def memory_ports(**overrides: Any) -> Ports:
    """Every port in memory: one ``MemoryRulebook`` for reads and search, empty profiles and
    obligations, the fake embedder, a ``ScriptedProvider`` with no script, a
    ``RecordingTracer``. ``overrides`` replace ports by name."""
    rulebook = MemoryRulebook()
    ports = Ports(
        rulebook=rulebook,
        search=rulebook,
        profiles=MemoryProfiles(),
        obligations=MemoryObligations(),
        embedder=FakeEmbedder(),
        provider=ScriptedProvider(),
        tracer=RecordingTracer(),
    )
    return replace(ports, **overrides)


class MemoryRulebook:
    """The rulebook's read API in memory: a ``RulebookReader`` and a ``ClauseSearch``."""

    def __init__(self) -> None:
        self.versions: dict[RuleVersionId, RuleVersion] = {}
        self.citations: dict[RuleVersionId, list[VersionCitation]] = {}
        self.clauses: dict[ClauseId, ClauseRecord] = {}
        self.entities: dict[CanonicalEntityId, Entity] = {}
        self.mentions: dict[CanonicalEntityId, list[ClauseId]] = {}
        self.relation_rows: list[Relation] = []
        self.calls: list[str] = []
        self.fail = False

    # ---- building the world ---------------------------------------------------------------

    def add_clause(
        self,
        text: str,
        *,
        clause_ref: str = "en.p1",
        document_id: DocumentId | None = None,
        external_ref: str = "",
        title: str = "",
        published_at: date | None = None,
    ) -> ClauseRecord:
        clause = ClauseRecord(
            clause_id=ClauseId(uuid4()),
            document_id=document_id or DocumentId(uuid4()),
            clause_ref=clause_ref,
            text=text,
            regulator="cbic",
            doc_type="notification",
            external_ref=external_ref,
            title=title,
            published_at=published_at,
        )
        self.clauses[clause.clause_id] = clause
        return clause

    def add_version(
        self,
        rule_key: str,
        *,
        effective_from: date,
        effective_to: date | None = None,
        version: int = 1,
        title: str = "",
        status: str = PUBLISHED,
        regulator: str = "cbic",
        specification: Mapping[str, object] | None = None,
    ) -> RuleVersion:
        rule = RuleVersion(
            rule_version_id=RuleVersionId(uuid4()),
            rule_key=rule_key,
            regulator=regulator,
            version=version,
            title=title or rule_key,
            effective_from=effective_from,
            effective_to=effective_to,
            status=status,
            specification=dict(specification or {}),
        )
        self.versions[rule.rule_version_id] = rule
        self.citations[rule.rule_version_id] = []
        return rule

    def cite(
        self, rule: RuleVersion, clause: ClauseRecord, quote: str, *, verified: bool = True
    ) -> VersionCitation:
        citation = VersionCitation(
            clause.clause_id, clause.document_id, clause.clause_ref, quote, verified
        )
        self.citations[rule.rule_version_id].append(citation)
        return citation

    def add_entity(
        self,
        entity_type: EntityType,
        name: str,
        *,
        aliases: Sequence[str] = (),
        mentioned_in: Iterable[ClauseRecord] = (),
    ) -> Entity:
        entity = Entity(
            CanonicalEntityId(uuid4()),
            entity_type,
            normalise_name(entity_type, name),
            tuple(normalise_name(entity_type, alias) for alias in aliases),
        )
        self.entities[entity.entity_id] = entity
        self.mentions[entity.entity_id] = [clause.clause_id for clause in mentioned_in]
        return entity

    def relate(
        self,
        source: RuleVersion,
        relation: RelationKind,
        target: RuleVersion | Entity,
        evidence: ClauseRecord,
        *,
        period_label: str | None = None,
        new_due_on: date | None = None,
    ) -> Relation:
        if isinstance(target, RuleVersion):
            to_kind, to_ref = RULE_VERSION_KIND, str(target.rule_version_id)
            to_rule, to_entity = target.rule_version_id, None
        else:
            to_kind, to_ref = target.entity_type.value, target.canonical_name
            to_rule, to_entity = None, target.entity_id
        row = Relation(
            relation_id=uuid4(),
            from_rule_version_id=source.rule_version_id,
            relation=relation,
            to_kind=to_kind,
            to_ref=to_ref,
            evidence_clause_id=evidence.clause_id,
            evidence_clause_ref=evidence.clause_ref,
            to_rule_version_id=to_rule,
            to_entity_id=to_entity,
            period_label=period_label,
            new_due_on=new_due_on,
        )
        self.relation_rows.append(row)
        return row

    def set_status(self, rule: RuleVersion, status: str) -> RuleVersion:
        changed = replace(rule, status=status)
        self.versions[rule.rule_version_id] = changed
        return changed

    # ---- RulebookReader ---------------------------------------------------------------------

    def rules_in_force(
        self, as_of: date, *, rule_key: str | None = None, regulator: str | None = None
    ) -> tuple[RuleVersion, ...]:
        self._read("rules_in_force")
        return tuple(
            sorted(
                (
                    rule
                    for rule in self.versions.values()
                    if _in_force(rule, as_of)
                    and rule_key in (None, rule.rule_key)
                    and regulator in (None, rule.regulator)
                ),
                key=lambda rule: rule.rule_key,
            )
        )

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionDetail | None:
        self._read("rule_version")
        rule = self.versions.get(rule_version_id)
        if rule is None:
            return None
        return RuleVersionDetail(rule, tuple(self.citations[rule_version_id]))

    def resolve_entity(self, entity_type: EntityType, name: str) -> EntityResolution:
        self._read("resolve_entity")
        normalised = normalise_name(entity_type, name)
        if not normalised:
            return EntityResolution(ResolutionStatus.EMPTY)
        of_type = [e for e in self.entities.values() if e.entity_type is entity_type]
        exact = [e for e in of_type if e.canonical_name == normalised]
        if exact:
            return EntityResolution(ResolutionStatus.RESOLVED, exact[0])
        aliased = tuple(e for e in of_type if normalised in e.aliases)
        if len(aliased) == 1:
            return EntityResolution(ResolutionStatus.RESOLVED, aliased[0])
        if aliased:
            return EntityResolution(ResolutionStatus.AMBIGUOUS, None, aliased)
        qualified = entity_type not in (EntityType.SECTION, EntityType.RULE) or "@" in normalised
        status = ResolutionStatus.NOT_FOUND if qualified else ResolutionStatus.UNQUALIFIED
        return EntityResolution(status)

    def entity_clauses(
        self, entity_id: CanonicalEntityId, *, as_of: date | None, limit: int
    ) -> tuple[ClauseRecord, ...]:
        self._read("entity_clauses")
        found = [self.clauses[clause_id] for clause_id in self.mentions.get(entity_id, [])]
        return tuple(
            self._dated(clause, as_of) for clause in found if _published_by(clause, as_of)
        )[:limit]

    def relations(
        self,
        *,
        from_rule_version_id: RuleVersionId | None = None,
        to_rule_version_id: RuleVersionId | None = None,
        to_entity_id: CanonicalEntityId | None = None,
    ) -> tuple[Relation, ...]:
        self._read("relations")
        return tuple(
            row
            for row in self.relation_rows
            if from_rule_version_id in (None, row.from_rule_version_id)
            and to_rule_version_id in (None, row.to_rule_version_id)
            and to_entity_id in (None, row.to_entity_id)
            and self.versions[row.from_rule_version_id].status in HAS_BEEN_PUBLISHED
        )

    def clause(self, clause_id: ClauseId) -> ClauseRecord | None:
        self._read("clause")
        return self.clauses.get(clause_id)

    # ---- ClauseSearch -------------------------------------------------------------------------

    def search(
        self,
        text: str,
        *,
        vector: Vector | None,
        model: str | None,
        as_of: date | None,
        k: int,
    ) -> tuple[SearchHit, ...]:
        self._read("search")
        if vector is not None and model is None:
            raise DependencyUnavailableError("rulebook: 422: a vector needs its model")
        words = _words(text)
        scored = [
            (len(words & _words(clause.text)), index, clause)
            for index, clause in enumerate(self.clauses.values())
            if _published_by(clause, as_of)
        ]
        ranked = sorted((item for item in scored if item[0]), key=lambda item: (-item[0], item[1]))
        return tuple(
            SearchHit(
                self._dated(clause, as_of), 1.0 / (60 + rank), self._cited_by(clause.clause_id)
            )
            for rank, (_, _, clause) in enumerate(ranked[:k], start=1)
        )

    def _dated(self, clause: ClauseRecord, as_of: date | None) -> ClauseRecord:
        """The clause with whether its rule is out of force on ``as_of``."""
        citing = [
            self.versions[rule_version_id]
            for rule_version_id, citations in self.citations.items()
            if self.versions[rule_version_id].status in WAS_PUBLISHED
            and any(c.clause_id == clause.clause_id and c.verified for c in citations)
        ]
        out = (
            as_of is not None
            and bool(citing)
            and not any(_in_force(rule, as_of) for rule in citing)
        )
        return replace(clause, out_of_force=out)

    def _cited_by(self, clause_id: ClauseId) -> tuple[RuleVersionId, ...]:
        return tuple(
            rule_version_id
            for rule_version_id, citations in self.citations.items()
            if self.versions[rule_version_id].status in HAS_BEEN_PUBLISHED
            and any(c.clause_id == clause_id and c.verified for c in citations)
        )

    def _read(self, name: str) -> None:
        self.calls.append(name)
        if self.fail:
            raise DependencyUnavailableError("rulebook: 503")


class MemoryProfiles:
    """Profile snapshots by tenant and business; JSON lists read as sets, as the HTTP client
    reads them."""

    def __init__(self) -> None:
        self.snapshots: dict[tuple[TenantId, BusinessId], ProfileSnapshot] = {}
        self.requests: list[tuple[TenantId, BusinessId, FinancialYear | None]] = []
        self.fail = False

    def add(
        self, tenant: TenantId, business: BusinessId, attributes: Mapping[str, object]
    ) -> ProfileSnapshot:
        snapshot = ProfileSnapshot(
            business_id=business,
            tenant_id=tenant,
            version=1,
            attributes={
                key: frozenset(value) if isinstance(value, list | tuple | set) else value
                for key, value in attributes.items()
            },
        )
        self.snapshots[tenant, business] = snapshot
        return snapshot

    def snapshot(
        self, tenant: TenantId, business: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        self.requests.append((tenant, business, fy))
        if self.fail:
            raise DependencyUnavailableError("profile: 503")
        found = self.snapshots.get((tenant, business))
        return None if found is None else replace(found, as_of_fy=fy)


class MemoryObligations:
    """Obligations by tenant; a due day is due at the end of that day in India."""

    def __init__(self) -> None:
        self.rows: dict[TenantId, list[ObligationRecord]] = {}
        self.requests: list[tuple[date | None, date | None]] = []
        self.fail = False

    def add(
        self,
        tenant: TenantId,
        business: BusinessId,
        rule: RuleVersion,
        title: str,
        due_on: date | None,
        *,
        status: ObligationStatus = ObligationStatus.OPEN,
        period_label: str | None = None,
    ) -> ObligationRecord:
        due_at = None if due_on is None else datetime.combine(due_on, time(23, 59, 59), INDIA)
        record = ObligationRecord(
            obligation_id=ObligationId(uuid4()),
            business_id=business,
            rule_version_id=rule.rule_version_id,
            title=title,
            status=status,
            period_label=period_label,
            due_at=due_at,
        )
        self.rows.setdefault(tenant, []).append(record)
        return record

    def obligations(
        self,
        tenant: TenantId,
        business: BusinessId,
        *,
        due_from: date | None = None,
        due_to: date | None = None,
        rule_version_id: RuleVersionId | None = None,
    ) -> tuple[ObligationRecord, ...]:
        self.requests.append((due_from, due_to))
        if self.fail:
            raise DependencyUnavailableError("obligation: 503")
        found = [
            row
            for row in self.rows.get(tenant, [])
            if row.business_id == business
            and rule_version_id in (None, row.rule_version_id)
            and (due_from is None or (row.due_on is not None and row.due_on >= due_from))
            and (due_to is None or (row.due_on is not None and row.due_on <= due_to))
        ]
        return tuple(sorted(found, key=lambda row: (row.due_at is None, row.due_at)))


def hash_vector(text: str, dims: int = EMBEDDING_DIMS) -> Vector:
    """A unit vector from the SHA-256 of ``text``: the same text always gets the same vector,
    and similar texts do not get similar ones. Not a model."""
    stream = b"".join(
        hashlib.sha256(f"{block}:{text}".encode()).digest() for block in range(dims // 32 + 1)
    )
    raw = [byte / 127.5 - 1.0 for byte in stream[:dims]]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return tuple(x / norm for x in raw)


class FakeEmbedder:
    """An ``Embedder`` that answers with ``hash_vector`` from the gateway's fake model; with
    ``fail`` set it is the gateway being down."""

    MODEL = "fake/hash-ngram-512"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[tuple[str, dict[str, str]]] = []

    def embed(
        self, text: str, *, tenant: TenantId | None, metadata: Mapping[str, str]
    ) -> QueryEmbedding:
        self.requests.append((text, dict(metadata)))
        if self.fail:
            raise DependencyUnavailableError("llm-gateway: embeddings unavailable")
        return QueryEmbedding(self.MODEL, hash_vector(text))


type Script = str | BaseException
"""One scripted reply: the model's text, or an exception to raise (a ``GatewayError`` stands in
for the gateway failing)."""


class UnscriptedCallError(LookupError):
    """A model call the script has no answer for."""


class ScriptedProvider:
    """An ``LLMProvider`` that answers from a script keyed by ``(question_id, prompt_ref)``,
    the question id being the ``question_id`` metadata every qa call carries. A value is one
    reply or a list served in order whose last item repeats. A call the script does not cover
    raises ``UnscriptedCallError``, so a test cannot pass on a model call it did not expect.
    Every request is kept in ``requests``. Not a model."""

    MODEL = "scripted/qa"

    def __init__(self, script: Mapping[tuple[str, str], Script | Sequence[Script]] | None = None):
        self.script: dict[tuple[str, str], Script | Sequence[Script]] = dict(script or {})
        self.requests: list[CompletionRequest] = []
        self._served: Counter[tuple[str, str]] = Counter()

    def add(self, question_id: str, prompt_ref: str, *replies: Script) -> None:
        self.script[question_id, prompt_ref] = list(replies)

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        self.requests.append(req)
        key = (req.metadata.get("question_id", ""), req.prompt_version)
        if key not in self.script:
            raise UnscriptedCallError(f"no scripted reply for {key}")
        entry = self.script[key]
        replies: Sequence[Script] = [entry] if isinstance(entry, str | BaseException) else entry
        reply = replies[min(self._served[key], len(replies) - 1)]
        self._served[key] += 1
        if isinstance(reply, BaseException):
            raise reply
        return CompletionResponse(text=reply, model=self.MODEL, input_tokens=0, output_tokens=0)

    def calls(self, prompt_ref: str) -> list[CompletionRequest]:
        return [req for req in self.requests if req.prompt_version == prompt_ref]


@dataclass
class RecordedSpan:
    name: str
    attributes: dict[str, AttributeValue] = field(default_factory=dict)
    failed: bool = False

    def set_attribute(self, key: str, value: AttributeValue) -> None:
        self.attributes[key] = value


class RecordingTracer:
    """A ``Tracer`` that keeps every span in the order it started; ``failed`` is set when an
    exception left the span."""

    def __init__(self) -> None:
        self.spans: list[RecordedSpan] = []

    @contextmanager
    def span(
        self, name: str, attributes: Mapping[str, AttributeValue] | None = None
    ) -> Iterator[RecordedSpan]:
        recorded = RecordedSpan(name, dict(attributes or {}))
        self.spans.append(recorded)
        try:
            yield recorded
        except BaseException:
            recorded.failed = True
            raise

    def named(self, name: str) -> list[RecordedSpan]:
        return [span for span in self.spans if span.name == name]


def plan_step(number: int, op: str, **fields: object) -> dict[str, object]:
    """Step ``s<number>`` of a scripted plan: every field null but the ones given."""
    step: dict[str, object] = dict.fromkeys(FIELDS)
    step.update(id=f"s{number}", op=op, **fields)
    return step


def plan_text(*steps: Mapping[str, object], as_of: str | None = None) -> str:
    """A scripted planner reply."""
    return json.dumps({"as_of": as_of, "steps": list(steps)})


def answer_text(answer: str, *citations: tuple[str, str], covered: bool = True) -> str:
    """A scripted answerer reply citing ``(label, quote)`` pairs."""
    return json.dumps(
        {
            "covered": covered,
            "answer": answer,
            "citations": [{"clause": label, "quote": quote} for label, quote in citations],
        }
    )


def _in_force(rule: RuleVersion, as_of: date) -> bool:
    return (
        rule.status in HAS_BEEN_PUBLISHED
        and rule.effective_from <= as_of
        and (rule.effective_to is None or as_of < rule.effective_to)
    )


def _published_by(clause: ClauseRecord, as_of: date | None) -> bool:
    published = clause.published_at
    return as_of is None or published is None or published <= as_of


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.casefold())) - _STOP_WORDS


def tenant_id(number: int) -> TenantId:
    """A fixed tenant id for tests."""
    return TenantId(UUID(int=number))
