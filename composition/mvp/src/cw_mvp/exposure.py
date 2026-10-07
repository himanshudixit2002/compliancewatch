"""Which listener serves each route: deny by default.

Every route a hosted service serves has one class:

- ``public``: user-facing routes, served on both listeners;
- ``admin``: the regulatory team's and operators' routes (rulebook review, its review tasks
  and publishing, the engine's review queue and fan-out controls, the gateway's prompts, models
  and usage, notification resends, the stored eval runs, the pipeline's source manager, uploads,
  task queue and operations). The public listener serves them only when
  ``CW_AUTH_MODE=token``, where each route itself requires an analyst, reviewer or admin a
  verified token names; in ``header`` and ``dual`` mode a request without a token could reach
  them, so they stay internal;
- ``internal``: service-to-service routes (identity's service tokens, channel consents and the
  memberships services check, notification's send, preferences and WhatsApp receipts, the
  rulebook's pipeline writes, the gateway's model calls, the engine's evaluations, which call the
  profile and the rulebook) and starting an eval run, which spends compute and model budget,
  served on the internal listener only.

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
        # Whether a user belongs to a tenant, for a service acting for it (tenant:act).
        "GET /v1/identity/users/{user_id}/membership": INTERNAL,
        # The audit trail: a tenant's owners read their tenant's rows; the regulatory team the
        # platform's. The route refuses staff, services, and a request without a token outside
        # header mode, and never shows the platform's rows to an anonymous caller.
        "GET /v1/identity/audit": PUBLIC,
        # What the tenant's plan entitles it to: a user's own tenant, or a service with
        # entitlements:read for the tenant it names (profile's registration check).
        "GET /v1/identity/entitlements": PUBLIC,
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
        # The public API's changes feed: the published changes, the same for every tenant.
        "GET /v1/changes": PUBLIC,
        # The analysts' review queues, decisions and the publish flow.
        "GET /v1/rulebook/rules": ADMIN,
        "GET /v1/rulebook/rules/{rule_key}/versions": ADMIN,
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
        # The review tasks: the queue a regulatory user reads, the seed tasks an analyst,
        # reviewer or admin opens, the claim, the draft from a candidate and the draft edit of
        # an analyst, and the decisions.
        "GET /v1/rulebook/review/tasks": ADMIN,
        "POST /v1/rulebook/review/tasks/seed": ADMIN,
        "GET /v1/rulebook/review/tasks/{task_id}": ADMIN,
        "POST /v1/rulebook/review/tasks/{task_id}/claim": ADMIN,
        "POST /v1/rulebook/review/tasks/{task_id}/draft": ADMIN,
        "PATCH /v1/rulebook/review/tasks/{task_id}/draft": ADMIN,
        "POST /v1/rulebook/review/tasks/{task_id}/decide": ADMIN,
        "GET /v1/rulebook/review/stats": ADMIN,
        # What the pipeline writes and reads back.
        "PUT /v1/rulebook/documents/{document_id}": INTERNAL,
        "PUT /v1/rulebook/documents/{document_id}/mentions": INTERNAL,
        "PUT /v1/rulebook/documents/{document_id}/relation-candidates": INTERNAL,
        "PUT /v1/rulebook/clauses/embeddings": INTERNAL,
        "GET /v1/rulebook/clauses/unembedded": INTERNAL,
    },
    "applicability-engine": {
        "GET /v1/applicability-engine/ping": INTERNAL,
        # A tenant's decisions, read by its members, and what a change means for its businesses
        # (the public API's impact of a change).
        "GET /v1/applicability-engine/businesses/{business_id}/decisions": PUBLIC,
        "GET /v1/applicability-engine/decisions/{decision_id}": PUBLIC,
        "GET /v1/changes/{rule_version_id}/impact": PUBLIC,
        # Evaluating reads the profile and the rulebook over the internal listener.
        "POST /v1/applicability-engine/businesses/{business_id}/decisions": INTERNAL,
        # The review queue: the regulatory team reads any tenant's items and settles them, which
        # appends a decision that makes or closes obligations. The routes require an analyst
        # (reading) or a reviewer or admin (settling) a verified token names, so the public
        # listener serves them in token mode only.
        "GET /v1/applicability-engine/review-items": ADMIN,
        "POST /v1/applicability-engine/review-items/{item_id}/resolve": ADMIN,
        # The fan-outs of published rule versions over every tenant's businesses: the regulatory
        # team reads them and the global hold, and an admin pauses, resumes or cancels a run and
        # sets or releases the hold, each audited. Every route requires a role a verified token
        # names, so the public listener serves them in token mode only.
        "GET /v1/applicability-engine/fan-outs": ADMIN,
        "GET /v1/applicability-engine/fan-outs/{rule_version_id}": ADMIN,
        "POST /v1/applicability-engine/fan-outs/{rule_version_id}/pause": ADMIN,
        "POST /v1/applicability-engine/fan-outs/{rule_version_id}/resume": ADMIN,
        "POST /v1/applicability-engine/fan-outs/{rule_version_id}/cancel": ADMIN,
        "GET /v1/applicability-engine/fan-out-hold": ADMIN,
        "PUT /v1/applicability-engine/fan-out-hold": ADMIN,
        # A dry run reads every tenant's profiles for an admin and stores nothing but its audit
        # entry; the route requires an admin a verified token names, so the public listener
        # serves it in token mode only.
        "POST /v1/applicability-engine/dry-runs": ADMIN,
    },
    "obligation": {
        "GET /v1/obligation/ping": PUBLIC,
        "GET /v1/obligation/obligations": PUBLIC,
        # Tracking, read by the tenant's members (and services acting for it) and changed by its
        # members, under the service's prefix for the web app and in the public API.
        "GET /v1/obligation/obligations/{obligation_id}": PUBLIC,
        "POST /v1/obligation/obligations/{obligation_id}/status": PUBLIC,
        "PUT /v1/obligation/obligations/{obligation_id}/assignee": PUBLIC,
        "POST /v1/obligation/obligations/{obligation_id}/comments": PUBLIC,
        "GET /v1/obligations/{obligation_id}": PUBLIC,
        "POST /v1/obligations/{obligation_id}/status": PUBLIC,
        "PUT /v1/obligations/{obligation_id}/assignee": PUBLIC,
        "POST /v1/obligations/{obligation_id}/comments": PUBLIC,
        # The public API's list of a business's obligations, beside profile's business routes.
        "GET /v1/businesses/{business_id}/obligations": PUBLIC,
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
        # The public API's bulk change card, for a CA firm's people (the route checks the role).
        "POST /v1/notification/bulk": PUBLIC,
        "POST /v1/notification/send": INTERNAL,
        "PUT /v1/notification/preferences/{channel}/{recipient}": INTERNAL,
        "GET /v1/notification/preferences/{channel}/{recipient}": INTERNAL,
        "POST /v1/notification/receipts/whatsapp": INTERNAL,
    },
    "qa": {
        "GET /v1/qa/ping": PUBLIC,
        "POST /v1/qa/ask": PUBLIC,
        # The public API's ask: the same handler as the route above.
        "POST /v1/qa": PUBLIC,
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
        # The source manager: the regulatory team reads the sources, their documents and the
        # stored files, and an admin adds and edits a source and starts a crawl, each audited.
        # The reads need a regulatory role and the writes an admin a verified token names, so
        # the public listener serves them in token mode only.
        "GET /v1/pipeline/sources": ADMIN,
        "POST /v1/pipeline/sources": ADMIN,
        "PATCH /v1/pipeline/sources/{key}": ADMIN,
        "POST /v1/pipeline/sources/{key}/fetch": ADMIN,
        "GET /v1/pipeline/sources/{key}/documents": ADMIN,
        "GET /v1/pipeline/documents/{document_id}": ADMIN,
        "GET /v1/pipeline/documents/{document_id}/raw": ADMIN,
        # An admin's upload of a document (the statutes the rules cite, a document a site
        # blocks), and the task queue: the regulatory team reads it, an admin resolves a manual
        # parse with a transcript or dismisses a task, each audited.
        "POST /v1/pipeline/sources/{key}/uploads": ADMIN,
        "GET /v1/pipeline/tasks": ADMIN,
        "POST /v1/pipeline/tasks/{task_id}/resolve": ADMIN,
        "POST /v1/pipeline/tasks/{task_id}/dismiss": ADMIN,
        # Operations: the regulatory team reads every source's crawl runs and documents and the
        # outbox's dead rows; an admin retries a stored document from a stage (with the type
        # they give it) and requeues a dead row, each audited with a reason.
        "GET /v1/pipeline/runs": ADMIN,
        "GET /v1/pipeline/documents": ADMIN,
        "POST /v1/pipeline/documents/{document_id}/retry": ADMIN,
        "GET /v1/pipeline/outbox/dead": ADMIN,
        "POST /v1/pipeline/outbox/{event_id}/requeue": ADMIN,
    },
}


def served_publicly(exposure: Exposure | None, auth_mode: AuthMode) -> bool:
    """Whether the public listener serves a route of this class; None is a route without one."""
    if exposure is Exposure.PUBLIC:
        return True
    return exposure is Exposure.ADMIN and auth_mode == "token"
