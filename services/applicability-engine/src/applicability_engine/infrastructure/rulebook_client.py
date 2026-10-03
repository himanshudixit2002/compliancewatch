"""The rulebook's ``GET /v1/rulebook/rule-versions/{rule_version_id}`` as the engine's
``RulebookReader``: the version's status and its specification, the kernel's predicate tree
mapping."""

from typing import Final
from uuid import UUID

import httpx2

from applicability_engine.domain.model import RuleVersionSpec
from applicability_engine.infrastructure.http import JsonHttp, http_client, reading
from domain_kernel.ids import RuleVersionId
from domain_kernel.predicates import specification_from_mapping
from domain_kernel.status import RuleVersionStatus

RULE_VERSION_PATH: Final = "/v1/rulebook/rule-versions/{rule_version_id}"
SERVICE: Final = "rulebook"


class HttpRulebook:
    """``base_url`` is ``CW_RULEBOOK_URL`` and ``auth`` the service's token auth (None sends no
    token). Pass ``client`` to talk to an in-process app (a FastAPI ``TestClient``) instead of the
    network."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._http = JsonHttp(http_client(base_url, timeout_seconds, client), SERVICE, auth=auth)

    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        data = self._http.get(RULE_VERSION_PATH.format(rule_version_id=rule_version_id))
        if data is None:
            return None
        with reading(SERVICE):
            return RuleVersionSpec(
                rule_version_id=RuleVersionId(UUID(str(data["rule_version_id"]))),
                status=RuleVersionStatus(data["status"]),
                specification=specification_from_mapping(data["specification"]),
            )

    def close(self) -> None:
        self._http.close()
