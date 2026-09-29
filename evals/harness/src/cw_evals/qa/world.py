"""The world the KAG golden cases are asked against, read from ``world.yaml`` and built in memory
through each service's own API.

``load_world`` reads the file: the recorded documents by their extraction case, the review
groups to decide, the rule versions (a seed rule takes its fields from the seed calendar, a
notification version carries its own), the relations to approve (relation golden cases), the
fictional businesses and the obligation window. ``build_world`` puts it together the way the
services would, each app in process behind a ``TestClient``:

- the rulebook (memory store, publishing on) registers each document through the pipeline's
  ``HttpRulebook``; the mention grammar's findings are aligned and each listed review group is
  decided with ``create_entity``;
- every version is created as a draft and cited; the relation stage stages each relation case's
  label (the label is the scripted model answer, as in the relation suite) and each candidate is
  approved from its version to its target; then the versions are submitted, approved and
  published in file order;
- the pipeline's embedding stage embeds every clause through the gateway;
- the profile service registers each business, one tenant each, and stores its attributes;
- the obligation store materialises each published recurring rule that applies to a business,
  then applies the deadline changes the publications announced.

``qa_app`` then builds the qa service on HTTP clients bound to those apps, with the KAG layer on
or off.
"""

import asyncio
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2
import yaml
from fastapi.testclient import TestClient

from cw_evals.relations import RelationCase, load_relation_case, scripted_answer
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import (
    BusinessId,
    DecisionId,
    DocumentId,
    RuleId,
    RuleVersionId,
    SourceId,
    TenantId,
)
from domain_kernel.knowledge import EntityType
from domain_kernel.ontology import Ontology
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import (
    Applicability,
    specification_from_mapping,
    specification_to_mapping,
)
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate, RuleVersionSnapshot
from obligation.application.changes import ApplyDeadlineChange, DeadlineChange
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.domain.events import RescheduleReason
from obligation.main import build_app as build_obligation
from obligation.settings import ObligationSettings
from ontology import load as load_ontology
from pipeline.application.embedding import EmbeddingStage
from pipeline.application.knowledge_activities import (
    ExtractMentions,
    MentionsRequest,
    ProposeRelations,
    RelationsRequest,
    SubmitRelations,
)
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.domain.knowledge import DocumentRecord
from pipeline.infrastructure.gateway import GatewayEmbedder
from pipeline.infrastructure.parsers.pdf import PARSER_VERSION
from pipeline.infrastructure.prompts import load_prompt
from pipeline.infrastructure.rulebook_client import HttpRulebook as PipelineRulebook
from pipeline.label import GoldenCase, load_case
from pipeline.testing import ScriptedProvider as RelationScript
from profile_service.main import build_app as build_profile
from profile_service.settings import ProfileSettings
from qa.infrastructure.gateway import GatewayProvider, HttpEmbedder
from qa.infrastructure.obligation_client import HttpObligations
from qa.infrastructure.profile_client import HttpProfiles
from qa.infrastructure.rulebook_client import HttpRulebook as QaRulebook
from qa.main import build_app as build_qa
from qa.testing import RecordingTracer, qa_settings
from qa.wiring import Ports
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.seed import SeedRule
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app as build_rulebook
from rulebook.testing import WRITE_TOKEN, rulebook_settings

WORLD_FILE: Final = Path("qa") / "kag" / "world.yaml"
RULEBOOK: Final = "/v1/rulebook"
PROFILE: Final = "/v1/profile"
AUTH: Final = {"x-cw-write-token": WRITE_TOKEN}
REGULATOR: Final = "CBIC"
RULE_REGULATOR: Final = "cbic"
MEDIA_TYPE: Final = "application/pdf"
SOURCE_ID: Final = UUID(int=0xE7A1)
"""The source the recorded notifications are registered under: made up, like the tenants."""
ANALYST: Final = UUID(int=0xA1)
DECIDED_BY: Final = "eval-world"
TENANT_BASE: Final = 0xE7A10000
"""Tenant ``n`` of the world is ``UUID(int=TENANT_BASE + n)``: one per business, made up."""
RELATION_PROMPT: Final = ("extraction.rule_relations", "1")


class WorldError(ValueError):
    """The world file is not usable."""


@dataclass(frozen=True, slots=True)
class ClauseQuote:
    """A quote of one clause of one of the world's documents."""

    document: str
    clause_ref: str
    quote: str


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    key: str
    extraction_case: str
    own_ref: str
    published_on: date
    published_on_support: ClauseQuote


@dataclass(frozen=True, slots=True)
class EntitySpec:
    entity_type: EntityType
    name: str


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """A version to publish. A seed rule reads every field but its citations from the seed
    calendar; a notification version names its title and start with the quote supporting it."""

    rule_key: str
    seed: bool
    citations: tuple[ClauseQuote, ...]
    title: str = ""
    effective_from: date | None = None
    effective_from_support: ClauseQuote | None = None


@dataclass(frozen=True, slots=True)
class RelationSpec:
    relation_case: str
    evidence_clause_ref: str
    from_rule: str
    target_rule: str | None


@dataclass(frozen=True, slots=True)
class BusinessSpec:
    key: str
    gstin: str
    name: str
    entity_name: str
    fys: tuple[str, ...]
    attributes: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class WorldSpec:
    world_id: str
    label_status: str
    labelled_by: str
    reviewed_by: str
    documents: tuple[DocumentSpec, ...]
    entities: tuple[EntitySpec, ...]
    rules: tuple[RuleSpec, ...]
    relations: tuple[RelationSpec, ...]
    businesses: tuple[BusinessSpec, ...]
    materialise_as_of: date
    windows: Mapping[str, int]
    cases: Mapping[str, GoldenCase] = field(repr=False)
    """The extraction case of each document, by document key: the clauses as recorded."""
    seed: Mapping[str, SeedRule] = field(repr=False)
    """The seed calendar's rules by key."""
    relation_cases: Mapping[str, RelationCase] = field(repr=False)
    """The relation golden cases the relations name, by path."""

    def document(self, key: str) -> DocumentSpec:
        for document in self.documents:
            if document.key == key:
                return document
        raise WorldError(f"no document {key!r} in the world")

    def clause_text(self, document: str, clause_ref: str) -> str | None:
        case = self.cases.get(document)
        clause = None if case is None else case.document.find_clause(clause_ref)
        return None if clause is None else clause.text

    def rule(self, rule_key: str) -> RuleSpec:
        for rule in self.rules:
            if rule.rule_key == rule_key:
                return rule
        raise WorldError(f"no rule {rule_key!r} in the world")

    def effective_from(self, rule_key: str) -> date:
        rule = self.rule(rule_key)
        if rule.seed:
            return self.seed[rule_key].effective_from
        if rule.effective_from is None:  # load_world refuses this
            raise WorldError(f"rule {rule_key!r} has no effective_from")
        return rule.effective_from

    def rules_in_force(self, as_of: date) -> frozenset[str]:
        """The rule keys whose version is in force on ``as_of``: every version here is
        published and open-ended, so it is in force from its start."""
        return frozenset(r.rule_key for r in self.rules if self.effective_from(r.rule_key) <= as_of)

    def business(self, key: str) -> BusinessSpec:
        for business in self.businesses:
            if business.key == key:
                return business
        raise WorldError(f"no business {key!r} in the world")


def load_world(golden: Path, ontology: Ontology | None = None) -> WorldSpec:
    """The world under ``golden`` (``evals/golden``); raises ``WorldError`` when a key or a
    reference does not resolve."""
    path = golden / WORLD_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        spec = _world(data, golden, ontology or load_ontology())
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, WorldError):
            raise
        raise WorldError(f"{path}: {exc}") from exc
    return spec


def _world(data: Any, golden: Path, ontology: Ontology) -> WorldSpec:
    if not isinstance(data, dict):
        raise WorldError("the world file must be a mapping")
    repo = golden.resolve().parent.parent
    calendar = load_calendar(ontology, repo / str(data["seed_calendar"]))
    documents = tuple(
        DocumentSpec(
            key=str(item["key"]),
            extraction_case=str(item["extraction_case"]),
            own_ref=str(item["own_ref"]),
            published_on=_day(item["published_on"]),
            published_on_support=_quote(item["published_on_support"], str(item["key"])),
        )
        for item in data["documents"]
    )
    cases = {doc.key: load_case(golden / doc.extraction_case) for doc in documents}
    rules = tuple(_rule(item) for item in data["rules"])
    relations = tuple(
        RelationSpec(
            relation_case=str(item["relation_case"]),
            evidence_clause_ref=str(item["evidence_clause_ref"]),
            from_rule=str(item["from_rule"]),
            target_rule=None if item.get("target_rule") is None else str(item["target_rule"]),
        )
        for item in data["relations"]
    )
    seed = {rule.rule_key: rule for rule in calendar.rules}
    keys = {rule.rule_key for rule in rules}
    for rule in rules:
        if rule.seed and rule.rule_key not in seed:
            raise WorldError(f"{rule.rule_key} is not a rule of the seed calendar")
    for relation in relations:
        for key in (relation.from_rule, relation.target_rule):
            if key is not None and key not in keys:
                raise WorldError(f"a relation names {key!r}, which is not a rule of the world")
    obligations = data["obligations"]
    return WorldSpec(
        world_id=str(data["world_id"]),
        label_status=str(data["label_status"]),
        labelled_by=str(data.get("labelled_by") or ""),
        reviewed_by=str(data.get("reviewed_by") or ""),
        documents=documents,
        entities=tuple(
            EntitySpec(EntityType(str(item["type"])), str(item["name"]))
            for item in data["entities"]
        ),
        rules=rules,
        relations=relations,
        businesses=tuple(
            BusinessSpec(
                key=str(item["key"]),
                gstin=str(item["gstin"]),
                name=str(item["name"]),
                entity_name=str(item["entity_name"]),
                fys=tuple(str(fy) for fy in item["fys"]),
                attributes=dict(item["attributes"]),
            )
            for item in data["businesses"]
        ),
        materialise_as_of=_day(obligations["materialise_as_of"]),
        windows={str(k): int(v) for k, v in dict(obligations["windows"]).items()},
        cases=cases,
        seed=seed,
        relation_cases={
            r.relation_case: load_relation_case(golden, golden / r.relation_case) for r in relations
        },
    )


def _rule(item: Mapping[str, Any]) -> RuleSpec:
    seed = bool(item.get("seed", False))
    citations = tuple(_quote(citation, str(citation["document"])) for citation in item["citations"])
    if seed:
        return RuleSpec(str(item["rule_key"]), True, citations)
    return RuleSpec(
        rule_key=str(item["rule_key"]),
        seed=False,
        citations=citations,
        title=str(item["title"]),
        effective_from=_day(item["effective_from"]),
        effective_from_support=_quote(
            item["effective_from_support"], str(item["effective_from_support"]["document"])
        ),
    )


def _quote(item: Mapping[str, Any], document: str) -> ClauseQuote:
    return ClauseQuote(document, str(item["clause_ref"]), str(item["quote"]))


def _day(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


# ---- building -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Services:
    """The world's apps in process and what building it created: tenants and profile nodes by
    business key, documents and clause ids by document key, versions by rule key."""

    spec: WorldSpec
    rulebook: TestClient
    profile: TestClient
    obligation: TestClient
    gateway: httpx2.Client
    tenants: Mapping[str, TenantId]
    businesses: Mapping[str, BusinessId]
    documents: Mapping[str, DocumentId]
    clause_ids: Mapping[tuple[str, str], UUID]
    versions: Mapping[str, RuleVersionId]
    open_groups: tuple[tuple[str, str], ...] = ()
    """Review groups left open (a section with no statute cannot name one entity)."""

    @property
    def default_tenant(self) -> TenantId:
        """The tenant a question with no business is asked as: the first business's."""
        return self.tenants[self.spec.businesses[0].key]

    def tenant_for(self, business: str | None) -> TenantId:
        return self.default_tenant if business is None else self.tenants[business]


@contextmanager
def build_world(spec: WorldSpec, gateway: httpx2.Client) -> Iterator[Services]:
    """The world's apps, seeded; ``gateway`` embeds the clauses and serves qa's model calls."""
    rulebook_app = build_rulebook(rulebook_settings(rulebook_publish_enabled=True))
    profile_app = build_profile(
        ProfileSettings(_env_file=None, service_name="profile", profile_store="memory")
    )
    obligation_app = build_obligation(
        ObligationSettings(_env_file=None, service_name="obligation", obligation_store="memory")
    )
    with (
        TestClient(rulebook_app) as rulebook,
        TestClient(profile_app) as profile,
        TestClient(obligation_app) as obligation,
    ):
        store: MemoryKnowledgeStore = rulebook_app.state.wiring.unit_of_work
        builder = _Builder(spec, rulebook, profile, obligation, gateway, store)
        builder.documents_and_entities()
        builder.versions_and_relations()
        builder.embed_clauses()
        builder.register_businesses()
        builder.materialise(obligation_app.state.wiring.unit_of_work)
        yield builder.services()


@contextmanager
def qa_app(services: Services, *, kag: bool) -> Iterator[TestClient]:
    """The qa service over the world, with the KAG layer on for every tenant or off."""
    rulebook = QaRulebook(client=services.rulebook)
    ports = Ports(
        rulebook=rulebook,
        search=rulebook,
        profiles=HttpProfiles(client=services.profile),
        obligations=HttpObligations(client=services.obligation),
        embedder=HttpEmbedder(client=services.gateway),
        provider=GatewayProvider(client=services.gateway),
        tracer=RecordingTracer(),
    )
    with TestClient(build_qa(qa_settings(qa_kag_enabled=kag), ports=ports)) as client:
        yield client


class _Builder:
    def __init__(
        self,
        spec: WorldSpec,
        rulebook: TestClient,
        profile: TestClient,
        obligation: TestClient,
        gateway: httpx2.Client,
        store: MemoryKnowledgeStore,
    ) -> None:
        self.spec = spec
        self.rulebook = rulebook
        self.profile = profile
        self.obligation = obligation
        self.gateway = gateway
        self.writer = PipelineRulebook(token=WRITE_TOKEN, client=rulebook)
        self.store = store
        self.ontology = load_ontology()
        self.documents: dict[str, DocumentId] = {}
        self.clause_ids: dict[tuple[str, str], UUID] = {}
        self.versions: dict[str, RuleVersionId] = {}
        self.tenants: dict[str, TenantId] = {}
        self.businesses: dict[str, BusinessId] = {}
        self.deadline_changes: list[tuple[RuleVersionId, str | None, date, RuleVersionId]] = []
        self.open_groups: tuple[tuple[str, str], ...] = ()

    def services(self) -> Services:
        return Services(
            spec=self.spec,
            rulebook=self.rulebook,
            profile=self.profile,
            obligation=self.obligation,
            gateway=self.gateway,
            tenants=dict(self.tenants),
            businesses=dict(self.businesses),
            documents=dict(self.documents),
            clause_ids=dict(self.clause_ids),
            versions=dict(self.versions),
            open_groups=self.open_groups,
        )

    # ---- documents, mentions, entities -------------------------------------------------

    def documents_and_entities(self) -> None:
        for spec in self.spec.documents:
            case = self.spec.cases[spec.key]
            document = replace(
                case.document, published_at=spec.published_on, parser_version=PARSER_VERSION
            )
            registered = self.writer.register_document(
                DocumentRecord(
                    document=document,
                    source_id=SourceId(SOURCE_ID),
                    sha256=str(case.source["sha256"]),
                    regulator=REGULATOR,
                    url=str(case.source["url"]),
                    media_type=MEDIA_TYPE,
                    fetched_at=_fetched_at(case.source.get("fetched_at")),
                    external_ref=spec.own_ref,
                )
            )
            self.documents[spec.key] = registered.document_id
            for ref, clause_id in registered.clause_ids.items():
                self.clause_ids[spec.key, ref] = clause_id.value
            asyncio.run(
                ExtractMentions(self.writer, self.writer, enabled=True).run(
                    MentionsRequest(document_id=registered.document_id.value, own_ref=spec.own_ref)
                )
            )
        for entity in self.spec.entities:
            _ok(
                self.rulebook.post(
                    f"{RULEBOOK}/review/entities/decisions",
                    json={
                        "entity_type": entity.entity_type.value,
                        "proposed_name": entity.name,
                        "decision": "create_entity",
                        "decided_by": DECIDED_BY,
                    },
                    headers=AUTH,
                ),
                f"create entity {entity.entity_type.value} {entity.name}",
            )
        groups = _ok(self.rulebook.get(f"{RULEBOOK}/review/entities"), "open review groups")
        self.open_groups = tuple((str(g["entity_type"]), str(g["proposed_name"])) for g in groups)

    # ---- versions, citations, relations, publication ---------------------------------------

    def versions_and_relations(self) -> None:
        for rule in self.spec.rules:
            self.versions[rule.rule_key] = self._draft(rule)
            citations = [
                {"clause_id": str(self._clause(c.document, c.clause_ref)), "quote": c.quote}
                for c in rule.citations
            ]
            _ok(
                self.rulebook.put(
                    f"{RULEBOOK}/rule-versions/{self.versions[rule.rule_key]}/citations",
                    json={"citations": citations},
                    headers=AUTH,
                ),
                f"cite {rule.rule_key}",
            )
        self._relations()
        actor = {"actor_id": str(ANALYST)}
        for rule in self.spec.rules:
            version = self.versions[rule.rule_key]
            for step in ("submit", "approve", "publish"):
                answer = _ok(
                    self.rulebook.post(
                        f"{RULEBOOK}/rule-versions/{version}/{step}", json=actor, headers=AUTH
                    ),
                    f"{step} {rule.rule_key}",
                )
            for change in answer["deadline_changes"]:
                self.deadline_changes.append(
                    (
                        RuleVersionId(UUID(str(change["rule_version_id"]))),
                        change["period_label"],
                        date.fromisoformat(str(change["new_due_on"])),
                        version,
                    )
                )

    def _draft(self, rule: RuleSpec) -> RuleVersionId:
        """A draft version in the rulebook's store, as the seed command writes one."""
        if not rule.seed:
            _, version = self.store.add_rule(
                rule.rule_key,
                title=rule.title,
                regulator=RULE_REGULATOR,
                effective_from=self.spec.effective_from(rule.rule_key),
            )
            return version
        seed = self.spec.seed[rule.rule_key]
        _, version = self.store.add_rule(
            seed.rule_key,
            title=seed.title,
            regulator=seed.regulator,
            level=seed.level,
            effective_from=seed.effective_from,
            summary=seed.summary,
            specification=specification_to_mapping(seed.specification),
            obligation_template=seed.obligation_template.to_mapping(),
            recurrence=None if seed.recurrence is None else seed.recurrence.to_mapping(),
        )
        return version

    def _relations(self) -> None:
        staged: set[str] = set()
        for relation in self.spec.relations:
            case = self.spec.relation_cases[relation.relation_case]
            document_key = self._document_key(case)
            document_id = self.documents[document_key]
            if relation.relation_case not in staged:
                staged.add(relation.relation_case)
                self._stage(case, document_id)
            evidence = self._clause(document_key, relation.evidence_clause_ref)
            candidates = _ok(
                self.rulebook.get(
                    f"{RULEBOOK}/review/relations",
                    params={"document_id": str(document_id), "limit": 200},
                ),
                f"relation candidates of {case.case_id}",
            )
            found = [c for c in candidates if UUID(str(c["evidence_clause_id"])) == evidence]
            if len(found) != 1:
                raise WorldError(
                    f"{relation.relation_case}: {len(found)} open candidates cite "
                    f"{relation.evidence_clause_ref}"
                )
            body: dict[str, object] = {
                "from_rule_version_id": str(self.versions[relation.from_rule]),
                "decided_by": DECIDED_BY,
            }
            if relation.target_rule is not None:
                body["target_rule_version_id"] = str(self.versions[relation.target_rule])
            _ok(
                self.rulebook.post(
                    f"{RULEBOOK}/review/relations/{found[0]['candidate_id']}/approve",
                    json=body,
                    headers=AUTH,
                ),
                f"approve {relation.relation_case} {relation.evidence_clause_ref}",
            )

    def _stage(self, case: RelationCase, document_id: DocumentId) -> None:
        ref = "{}@{}".format(*RELATION_PROMPT)
        script = RelationScript({(str(document_id), ref): scripted_answer(case)})
        stage = RelationStage(LlmRelationExtractor(script, load_prompt(*RELATION_PROMPT)))
        request = RelationsRequest(
            document_id=document_id.value, own_ref=case.own_ref, regulator=REGULATOR
        )
        batch = asyncio.run(ProposeRelations(self.writer, stage, enabled=True).run(request))
        asyncio.run(SubmitRelations(self.writer, enabled=True).run(batch))

    def _document_key(self, case: RelationCase) -> str:
        for key, extraction in self.spec.cases.items():
            if extraction.document.document_id == case.document.document_id:
                return key
        raise WorldError(f"relation case {case.case_id} is about a document not in the world")

    def _clause(self, document: str, clause_ref: str) -> UUID:
        try:
            return self.clause_ids[document, clause_ref]
        except KeyError:
            raise WorldError(f"{document} has no clause {clause_ref}") from None

    # ---- search index -------------------------------------------------------------------------

    def embed_clauses(self) -> None:
        EmbeddingStage(GatewayEmbedder(client=self.gateway), self.writer).embed_missing(None)

    # ---- businesses and obligations ---------------------------------------------------------

    def register_businesses(self) -> None:
        for number, business in enumerate(self.spec.businesses, start=1):
            tenant = TenantId(UUID(int=TENANT_BASE + number))
            headers = {"x-tenant-id": str(tenant)}
            node = _ok(
                self.profile.post(
                    f"{PROFILE}/registrations",
                    json={
                        "gstin": business.gstin,
                        "name": business.name,
                        "entity_name": business.entity_name,
                    },
                    headers=headers,
                ),
                f"register {business.key}",
            )
            changes: dict[str, list[dict[str, object]]] = {}
            for key, value in business.attributes.items():
                definition = self.ontology.require(key)
                registration = definition.level.value == "registration"
                target = node["id"] if registration else node["parent_id"]
                years: Sequence[str | None] = (
                    business.fys if definition.per_financial_year else (None,)
                )
                for fy in years:
                    change: dict[str, object] = {"key": key, "value": value}
                    if fy is not None:
                        change["as_of_fy"] = fy
                    changes.setdefault(str(target), []).append(change)
            for target, items in changes.items():
                _ok(
                    self.profile.put(
                        f"{PROFILE}/nodes/{target}/attributes",
                        json={"changes": items, "source": "user_input"},
                        headers=headers,
                    ),
                    f"attributes of {business.key}",
                )
            self.tenants[business.key] = tenant
            self.businesses[business.key] = BusinessId(UUID(str(node["id"])))

    def materialise(self, unit_of_work: Any) -> None:
        as_of = self.spec.materialise_as_of
        fy = FinancialYear.for_date(as_of).label
        for business in self.spec.businesses:
            tenant, node = self.tenants[business.key], self.businesses[business.key]
            snapshot = _ok(
                self.profile.get(
                    f"{PROFILE}/nodes/{node}/snapshot",
                    params={"fy": fy},
                    headers={"x-tenant-id": str(tenant)},
                ),
                f"snapshot of {business.key}",
            )
            attributes = {
                key: frozenset(value) if isinstance(value, list) else value
                for key, value in dict(snapshot["attributes"]).items()
            }
            for rule in self.spec.rules:
                version = self._snapshot(self.versions[rule.rule_key])
                if version is None or version.recurrence is None:
                    continue
                if version.specification.evaluate(attributes, self.ontology) is not (
                    Applicability.APPLIES
                ):
                    continue
                window = self.spec.windows[version.recurrence.frequency.value]
                MaterialiseObligations(unit_of_work, window=window).run(
                    MaterialiseRequest(tenant, node, DecisionId.new(), version, as_of)
                )
            for target, period, new_due_on, caused_by in self.deadline_changes:
                ApplyDeadlineChange(unit_of_work).run(
                    DeadlineChange(
                        tenant_id=tenant,
                        rule_version_id=target,
                        period_label=period,
                        new_due_on=new_due_on,
                        reason=RescheduleReason.DEADLINE_EXTENDED,
                        caused_by=caused_by,
                    )
                )

    def _snapshot(self, version_id: RuleVersionId) -> RuleVersionSnapshot | None:
        data = _ok(
            self.rulebook.get(f"{RULEBOOK}/rule-versions/{version_id}"), f"version {version_id}"
        )
        if not data["obligation_template"]:
            return None
        effective_to = data.get("effective_to")
        return RuleVersionSnapshot(
            rule_id=RuleId(UUID(str(data["rule_id"]))),
            rule_version_id=version_id,
            version=int(data["version"]),
            regulator=str(data["regulator"]),
            title=str(data["title"]),
            specification=specification_from_mapping(dict(data["specification"])),
            effective=EffectivePeriod(
                date.fromisoformat(str(data["effective_from"])),
                None if effective_to is None else date.fromisoformat(str(effective_to)),
            ),
            obligation_template=ObligationTemplate.from_mapping(data["obligation_template"]),
            recurrence=None
            if data.get("recurrence") is None
            else Recurrence.from_mapping(data["recurrence"]),
        )


def _fetched_at(value: object) -> datetime:
    if value is None:
        return datetime(2026, 9, 28, tzinfo=UTC)
    return datetime.fromisoformat(str(value))


def _ok(response: httpx2.Response, what: str) -> Any:
    if response.status_code not in (200, 201):
        raise WorldError(f"{what}: {response.status_code} {response.text[:500]}")
    return response.json()
