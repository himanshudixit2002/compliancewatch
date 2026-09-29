"""The rulebook's open read API as the qa service's ``RulebookReader`` and ``ClauseSearch``."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Final
from uuid import UUID

import httpx2

from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleVersionId
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.vectors import Vector
from qa.domain.records import (
    ClauseRecord,
    Entity,
    EntityResolution,
    Relation,
    ResolutionStatus,
    RuleVersion,
    RuleVersionDetail,
    SearchHit,
    VersionCitation,
)
from qa.infrastructure.http import JsonHttp, http_client, reading

PREFIX: Final = "/v1/rulebook"
PAGE: Final = 500
"""Rule versions per page of ``GET /rule-versions``, the most the rulebook serves."""
RELATIONS: Final = 500
SERVICE: Final = "rulebook"


class HttpRulebook:
    """``base_url`` is ``CW_RULEBOOK_URL``. Pass ``client`` to talk to an in-process app (a
    FastAPI ``TestClient``) instead of the network."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        *,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._http = JsonHttp(http_client(base_url, timeout_seconds, client), SERVICE)

    def rules_in_force(
        self, as_of: date, *, rule_key: str | None = None, regulator: str | None = None
    ) -> tuple[RuleVersion, ...]:
        found: list[RuleVersion] = []
        after: str | None = None
        while True:
            params: dict[str, str | int] = {"as_of": as_of.isoformat(), "limit": PAGE}
            for name, value in (("rule_key", rule_key), ("regulator", regulator), ("after", after)):
                if value is not None:
                    params[name] = value
            page = self._http.get(f"{PREFIX}/rule-versions", params=params) or []
            with reading(SERVICE):
                found.extend(_version(item) for item in page)
                if len(page) < PAGE:
                    return tuple(found)
                after = str(page[-1]["rule_key"])

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionDetail | None:
        data = self._http.get(f"{PREFIX}/rule-versions/{rule_version_id}")
        if data is None:
            return None
        with reading(SERVICE):
            return RuleVersionDetail(
                _version(data), tuple(_citation(item) for item in data["citations"])
            )

    def resolve_entity(self, entity_type: EntityType, name: str) -> EntityResolution:
        params = {"type": entity_type.value, "name": name}
        data = self._http.get(f"{PREFIX}/entities/resolve", params=params)
        with reading(SERVICE):
            found = data["entity"]
            return EntityResolution(
                status=ResolutionStatus(data["status"]),
                entity=None if found is None else _entity(found),
                candidates=tuple(_entity(item) for item in data["candidates"]),
            )

    def entity_clauses(
        self, entity_id: CanonicalEntityId, *, as_of: date | None, limit: int
    ) -> tuple[ClauseRecord, ...]:
        params: dict[str, str | int] = {"limit": limit}
        if as_of is not None:
            params["as_of"] = as_of.isoformat()
        data = self._http.get(f"{PREFIX}/entities/{entity_id}/clauses", params=params) or []
        with reading(SERVICE):
            return tuple(_clause(item) for item in data)

    def relations(
        self,
        *,
        from_rule_version_id: RuleVersionId | None = None,
        to_rule_version_id: RuleVersionId | None = None,
        to_entity_id: CanonicalEntityId | None = None,
    ) -> tuple[Relation, ...]:
        params: dict[str, str | int] = {"limit": RELATIONS}
        ends = (
            ("from_rule_version_id", from_rule_version_id),
            ("to_rule_version_id", to_rule_version_id),
            ("to_entity_id", to_entity_id),
        )
        for name, value in ends:
            if value is not None:
                params[name] = str(value)
        data = self._http.get(f"{PREFIX}/relations", params=params) or []
        with reading(SERVICE):
            return tuple(_relation(item) for item in data)

    def clause(self, clause_id: ClauseId) -> ClauseRecord | None:
        data = self._http.get(f"{PREFIX}/clauses/{clause_id}")
        if data is None:
            return None
        with reading(SERVICE):
            return _clause(data)

    def search(
        self,
        text: str,
        *,
        vector: Vector | None,
        model: str | None,
        as_of: date | None,
        k: int,
    ) -> tuple[SearchHit, ...]:
        body: dict[str, object] = {"text": text, "k": k}
        if vector is not None:
            body.update(vector=list(vector), model=model)
        if as_of is not None:
            body["as_of"] = as_of.isoformat()
        data = self._http.post(f"{PREFIX}/search", body) or []
        with reading(SERVICE):
            return tuple(
                SearchHit(
                    clause=_clause(item),
                    score=float(item["score"]),
                    cited_by=tuple(RuleVersionId(UUID(str(v))) for v in item["cited_by"]),
                )
                for item in data
            )

    def close(self) -> None:
        self._http.close()


def _version(item: Mapping[str, Any]) -> RuleVersion:
    return RuleVersion(
        rule_version_id=RuleVersionId(UUID(str(item["rule_version_id"]))),
        rule_key=str(item["rule_key"]),
        regulator=str(item["regulator"]),
        version=int(item["version"]),
        title=str(item["title"]),
        effective_from=date.fromisoformat(str(item["effective_from"])),
        effective_to=_date(item.get("effective_to")),
        status=str(item["status"]),
        summary=str(item.get("summary") or ""),
        specification=dict(item.get("specification") or {}),
        obligation_template=dict(item.get("obligation_template") or {}),
    )


def _citation(item: Mapping[str, Any]) -> VersionCitation:
    return VersionCitation(
        clause_id=ClauseId(UUID(str(item["clause_id"]))),
        document_id=DocumentId(UUID(str(item["document_id"]))),
        clause_ref=str(item["clause_ref"]),
        quote=str(item["quote"]),
        verified=bool(item["verified"]),
    )


def _entity(item: Mapping[str, Any]) -> Entity:
    return Entity(
        entity_id=CanonicalEntityId(UUID(str(item["entity_id"]))),
        entity_type=EntityType(item["entity_type"]),
        canonical_name=str(item["canonical_name"]),
        aliases=tuple(str(alias) for alias in item.get("aliases", [])),
    )


def _clause(item: Mapping[str, Any]) -> ClauseRecord:
    return ClauseRecord(
        clause_id=ClauseId(UUID(str(item["clause_id"]))),
        document_id=DocumentId(UUID(str(item["document_id"]))),
        clause_ref=str(item["clause_ref"]),
        text=str(item["text"]),
        regulator=str(item.get("regulator") or ""),
        doc_type=str(item.get("doc_type") or ""),
        external_ref=str(item.get("external_ref") or ""),
        title=str(item.get("title") or ""),
        published_at=_date(item.get("published_at")),
        out_of_force=bool(item.get("out_of_force", False)),
    )


def _relation(item: Mapping[str, Any]) -> Relation:
    to_rule = item.get("to_rule_version_id")
    to_entity = item.get("to_entity_id")
    return Relation(
        relation_id=UUID(str(item["relation_id"])),
        from_rule_version_id=RuleVersionId(UUID(str(item["from_rule_version_id"]))),
        relation=RelationKind(item["relation"]),
        to_kind=str(item["to_kind"]),
        to_ref=str(item["to_ref"]),
        evidence_clause_id=ClauseId(UUID(str(item["evidence_clause_id"]))),
        evidence_clause_ref=str(item["evidence_clause_ref"]),
        to_rule_version_id=None if to_rule is None else RuleVersionId(UUID(str(to_rule))),
        to_entity_id=None if to_entity is None else CanonicalEntityId(UUID(str(to_entity))),
        period_label=None if item.get("period_label") is None else str(item["period_label"]),
        new_due_on=_date(item.get("new_due_on")),
    )


def _date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value)
    return datetime.fromisoformat(text).date() if "T" in text else date.fromisoformat(text)
