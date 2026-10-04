"""Which listener serves each route: deny by default.

Every route a hosted service serves has one class:

- ``public``: user-facing routes, served on both listeners;
- ``admin``: the regulatory team's and operators' routes (rulebook review and publishing, the
  gateway's prompts, models and usage, notification resends, the stored eval runs). The public
  listener serves them only when ``CW_AUTH_MODE=token``, where each route itself requires an
  analyst, reviewer or admin a verified token names; in ``header`` and ``dual`` mode a request
  without a token could reach them, so they stay internal;
- ``internal``: service-to-service routes (identity's service tokens and channel consents,
  notification's send, preferences and WhatsApp receipts, the rulebook's pipeline writes, the
  gateway's model calls, the engine's evaluations, which call the profile and the rulebook) and
  starting an eval run, which spends compute and model budget, served on the internal listener
  only.

The internal listener, on the private network, serves every route. The public listener answers
any route without a class, and any path no service serves, with the same 404
``route-not-found``. ``EXPOSURE`` lists every route of every service as ``METHOD /path`` in the
path's template form; ``tests/unit/test_exposure.py`` fails on a served route missing from it
and on a listed route no service serves, so a package that adds a route classes it here in the
same change. ``/health`` and ``/ready`` are the app's own, public on both listeners.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from py_common.settings import AuthMode


class Exposure(StrEnum):
    PUBLIC = "public"
    ADMIN = "admin"
    INTERNAL = "internal"


PUBLIC: Final = Exposure.PUBLIC
ADMIN: Final = Exposure.ADMIN
INTERNAL: Final = Exposure.INTERNAL

ROOT_ROUTES: Final = frozenset({"GET /health", "GET /ready"})
"""The app's own routes, public: the platform's probes."""

EXPOSURE: Final[Mapping[str, Mapping[str, Exposure]]] = {
    "identity": {
        "GET /v1/identity/ping": PUBLIC,
        "POST /v1/identity/consents": PUBLIC,
        "GET /v1/identity/consents": PUBLIC,
        "POST /v1/identity/channel-consents": INTERNAL,
        "GET /v1/identity/channel-consents/{channel}/{subject}": INTERNAL,
        "GET /v1/identity/billing/plans": PUBLIC,
        "POST /v1/identity/billing/subscriptions": PUBLIC,
        "POST /v1/identity/billing/webhook": PUBLIC,
        "POST /v1/identity/sessions": PUBLIC,
        "POST /v1/identity/service-tokens": INTERNAL,
        "GET /v1/identity/.well-known/jwks.json": PUBLIC,
        "GET /v1/identity/me": PUBLIC,
        "POST /v1/identity/dev/provider-tokens": PUBLIC,
        "POST /v1/identity/tenants": PUBLIC,
        "GET /v1/identity/users": PUBLIC,
        "POST /v1/identity/users": PUBLIC,
        "PUT /v1/identity/users/{user_id}/roles": PUBLIC,
        "POST /v1/identity/users/{user_id}/disable": PUBLIC,
    },
    "profile": {
        "GET /v1/profile/ping": PUBLIC,
        "POST /v1/profile/entities": PUBLIC,
        "POST /v1/profile/registrations": PUBLIC,
        "POST /v1/profile/locations": PUBLIC,
        "GET /v1/profile/nodes/{node_id}": PUBLIC,
        "PUT /v1/profile/nodes/{node_id}/attributes": PUBLIC,
        "GET /v1/profile/nodes/{node_id}/snapshot": PUBLIC,
        "GET /v1/profile/nodes/{node_id}/next-question": PUBLIC,
        "GET /v1/profile/nodes/{node_id}/review-tasks": PUBLIC,
        "POST /v1/profile/registrations/{node_id}/prefill": PUBLIC,
        "POST /v1/profile/financial-year-confirmations": PUBLIC,
        "POST /v1/businesses": PUBLIC,
        "GET /v1/businesses": PUBLIC,
        "GET /v1/businesses/{business_id}": PUBLIC,
        "PATCH /v1/businesses/{business_id}": PUBLIC,
        "GET /v1/businesses/{business_id}/onboarding": PUBLIC,
        "POST /v1/businesses/{business_id}/registrations": PUBLIC,
        "GET /v1/ontology": PUBLIC,
    },
    "rulebook": {
        "GET /v1/rulebook/ping": INTERNAL,
        # The reads every tenant makes: the published rulebook and its search.
        "GET /v1/rulebook/rule-versions": PUBLIC,
        "GET /v1/rulebook/rule-versions/{rule_version_id}": PUBLIC,
        "GET /v1/rulebook/rule-versions/{rule_version_id}/citations": PUBLIC,
        "GET /v1/rulebook/entities/resolve": PUBLIC,
        "GET /v1/rulebook/entities/{entity_id}": PUBLIC,
        "GET /v1/rulebook/entities/{entity_id}/clauses": PUBLIC,
        "GET /v1/rulebook/relations": PUBLIC,
        "GET /v1/rulebook/clauses/{clause_id}": PUBLIC,
        "POST /v1/rulebook/search": PUBLIC,
        # The analysts' review queues, decisions and the publish flow.
        "GET /v1/rulebook/rules": ADMIN,
        "GET /v1/rulebook/documents/{document_id}": ADMIN,
        "GET /v1/rulebook/review/entities": ADMIN,
        "GET /v1/rulebook/review/entities/items": ADMIN,
        "POST /v1/rulebook/review/entities/decisions": ADMIN,
        "GET /v1/rulebook/review/relations": ADMIN,
        "POST /v1/rulebook/review/relations/{candidate_id}/approve": ADMIN,
        "POST /v1/rulebook/review/relations/{candidate_id}/reject": ADMIN,
        "PUT /v1/rulebook/rule-versions/{rule_version_id}/citations": ADMIN,
        "POST /v1/rulebook/rule-versions/{rule_version_id}/submit": ADMIN,
        "POST /v1/rulebook/rule-versions/{rule_version_id}/return": ADMIN,
        "POST /v1/rulebook/rule-versions/{rule_version_id}/approve": ADMIN,
        "POST /v1/rulebook/rule-versions/{rule_version_id}/publish": ADMIN,
        "POST /v1/rulebook/rule-versions/{rule_version_id}/withdraw": ADMIN,
        "POST /v1/rulebook/maintenance/transitions": ADMIN,
        # What the pipeline writes and reads back.
        "PUT /v1/rulebook/documents/{document_id}": INTERNAL,
        "PUT /v1/rulebook/documents/{document_id}/mentions": INTERNAL,
        "PUT /v1/rulebook/documents/{document_id}/relation-candidates": INTERNAL,
        "PUT /v1/rulebook/clauses/embeddings": INTERNAL,
        "GET /v1/rulebook/clauses/unembedded": INTERNAL,
    },
    "applicability-engine": {
        "GET /v1/applicability-engine/ping": INTERNAL,
        # A tenant's decisions, read by its members.
        "GET /v1/applicability-engine/businesses/{business_id}/decisions": PUBLIC,
        "GET /v1/applicability-engine/decisions/{decision_id}": PUBLIC,
        # Evaluating reads the profile and the rulebook over the internal listener.
        "POST /v1/applicability-engine/businesses/{business_id}/decisions": INTERNAL,
    },
    "obligation": {
        "GET /v1/obligation/ping": PUBLIC,
        "GET /v1/obligation/obligations": PUBLIC,
    },
    "notification": {
        "GET /v1/notification/ping": PUBLIC,
        "GET /v1/notification/templates": PUBLIC,
        "GET /v1/notification/recipients": PUBLIC,
        "PUT /v1/notification/recipients/{recipient_id}": PUBLIC,
        "GET /v1/notification/recipients/{recipient_id}": PUBLIC,
        "DELETE /v1/notification/recipients/{recipient_id}": PUBLIC,
        "GET /v1/notification/notifications": PUBLIC,
        "GET /v1/notification/notifications/{notification_id}": PUBLIC,
        # SES reports bounces and complaints here, with the feedback token.
        "POST /v1/notification/receipts/email": PUBLIC,
        "POST /v1/notification/notifications/{notification_id}/resend": ADMIN,
        "POST /v1/notification/send": INTERNAL,
        "PUT /v1/notification/preferences/{channel}/{recipient}": INTERNAL,
        "GET /v1/notification/preferences/{channel}/{recipient}": INTERNAL,
        "POST /v1/notification/receipts/whatsapp": INTERNAL,
    },
    "qa": {
        "GET /v1/qa/ping": PUBLIC,
        "POST /v1/qa/ask": PUBLIC,
    },
    "llm-gateway": {
        "GET /v1/llm-gateway/ping": INTERNAL,
        "GET /v1/llm-gateway/usage": ADMIN,
        "GET /v1/llm-gateway/models": ADMIN,
        "GET /v1/llm-gateway/prompts": ADMIN,
        "POST /v1/llm-gateway/completions": INTERNAL,
        "POST /v1/llm-gateway/embeddings": INTERNAL,
    },
    "eval": {
        "GET /v1/eval/ping": INTERNAL,
        # The stored runs and their gates, for the regulatory team.
        "GET /v1/eval/runs": ADMIN,
        "GET /v1/eval/runs/{run_id}": ADMIN,
        # A run spends compute and, under the nightly profile, model budget.
        "POST /v1/eval/runs": INTERNAL,
    },
    "pipeline": {
        "GET /v1/pipeline/ping": INTERNAL,
    },
}


def served_publicly(exposure: Exposure | None, auth_mode: AuthMode) -> bool:
    """Whether the public listener serves a route of this class; None is a route without one."""
    if exposure is Exposure.PUBLIC:
        return True
    return exposure is Exposure.ADMIN and auth_mode == "token"
