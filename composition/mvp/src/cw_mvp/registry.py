"""Every service this deployable hosts, and the settings each one runs on.

``REGISTRY`` has one ``ServiceEntry`` per directory under ``services/``, identity first: the
app process builds identity before the others and hands its authenticator to all of them. An
entry names:

- ``name``, the service directory, which is also its route prefix ``/v1/<name>``;
- ``schema``, its Postgres schema (the Makefile's ``SCHEMA_*`` and ``infra/dev/postgres/init.sql``);
- ``settings_type`` and ``build``, the service's settings class and ``<pkg>.main.build_app``;
- ``components``, ``<pkg>.worker.components`` for a service with background work;
- ``url_fields``, the settings that hold the URL of another service, all set to the internal
  listener; a field ``<service>_url`` points at that service. Every service gets
  ``identity_url`` from the shared settings, so ``calls_identity`` says a service's routes call
  identity;
- ``loopback_routes``, the routes (``METHOD /path``) that call other services over the internal
  listener while they serve a request. The app runs at most ``CW_MVP_LOOPBACK_LIMIT`` of them at
  once, and the routes they call make no such calls themselves (one level deep), so the calls
  they make always find a free thread;
- ``called_routes``, for a service with loopback routes of its own that another service's
  loopback routes call: the routes those calls reach, none of them a loopback route;
- ``takes_authenticator`` and ``takes_token_source``, whether ``build`` accepts identity's
  authenticator and a source of service tokens minted in the process.

An entry's ``store_field`` is the setting that picks where the service keeps its state,
``<service>_store`` (``obligation_store``), when its settings have one. A setting that picks
where a service keeps files rather than its state ends in ``_raw_store`` instead, such as the
pipeline's ``pipeline_raw_store``: the worker shares no state through it, and check-config has
its own rule for it.

A package that adds ``build_app`` arguments, worker components, URL settings or routes that call
other services registers them here in the same change; ``tests/unit/test_registry.py`` fails
until it does. ``service_settings(entry, root)`` builds an entry's settings.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fastapi import FastAPI

from applicability_engine.main import build_app as build_applicability_engine
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.worker import components as applicability_engine_components
from eval_service.main import build_app as build_eval
from eval_service.settings import EvalSettings
from identity.main import build_app as build_identity
from identity.settings import IdentitySettings
from llm_gateway.main import build_app as build_llm_gateway
from llm_gateway.settings import GatewaySettings
from notification.main import build_app as build_notification
from notification.settings import NotificationSettings
from notification.worker import components as notification_components
from obligation.main import build_app as build_obligation
from obligation.settings import ObligationSettings
from obligation.worker import components as obligation_components
from pipeline.main import build_app as build_pipeline
from pipeline.settings import PipelineSettings
from pipeline.worker import components as pipeline_components
from profile_service.main import build_app as build_profile
from profile_service.settings import ProfileSettings
from py_common.runtime import WorkerComponents
from py_common.settings import Settings, with_search_path
from qa.main import build_app as build_qa
from qa.settings import QaSettings
from rulebook.main import build_app as build_rulebook
from rulebook.settings import RulebookSettings
from rulebook.worker import components as rulebook_components

JWKS_PATH: Final = "/v1/identity/.well-known/jwks.json"
URL_SUFFIX: Final = "_url"
STORE_SUFFIX: Final = "_store"
RAW_STORE_SUFFIX: Final = "_raw_store"
"""A setting that picks where a service keeps files, not its state (``pipeline_raw_store``)."""
SHARED_FIELDS_SET_PER_SERVICE: Final = frozenset({"service_name", "database_url", "db_schema"})
"""The shared settings each service gets its own value of; the rest are the root's."""


@dataclass(frozen=True, slots=True)
class ServiceEntry[S: Settings]:
    name: str
    schema: str
    settings_type: type[S]
    build: Callable[..., FastAPI]
    components: Callable[[S], WorkerComponents] | None = None
    url_fields: tuple[str, ...] = ()
    loopback_routes: tuple[str, ...] = ()
    called_routes: tuple[str, ...] = ()
    takes_authenticator: bool = True
    takes_token_source: bool = False
    calls_identity: bool = False

    def __post_init__(self) -> None:
        for field in self.url_fields:
            if not field.endswith(URL_SUFFIX) or field not in self.settings_type.model_fields:
                raise ValueError(f"{self.name}: {field!r} is not a URL field of its settings")

    @property
    def prefix(self) -> str:
        """Where its routes are, the facade paths of the public API aside."""
        return f"/v1/{self.name}"

    @property
    def calls(self) -> tuple[str, ...]:
        """The services it calls: ``rulebook_url`` names rulebook, ``llm_gateway_url``
        llm-gateway, and identity with ``calls_identity``."""
        named = tuple(field.removesuffix(URL_SUFFIX).replace("_", "-") for field in self.url_fields)
        return (("identity",) if self.calls_identity else ()) + named

    @property
    def store_field(self) -> str | None:
        """The setting that picks its store, ``applicability_engine_store`` for
        applicability-engine; None for a service without one."""
        field = self.name.replace("-", "_") + STORE_SUFFIX
        return field if field in self.settings_type.model_fields else None


REGISTRY: Final[tuple[ServiceEntry[Any], ...]] = (
    ServiceEntry(
        "identity", "identity", IdentitySettings, build_identity, takes_authenticator=False
    ),
    ServiceEntry(
        "profile",
        "profile",
        ProfileSettings,
        build_profile,
        # A new GSTIN registration reads the tenant's entitlements at identity while the flag
        # identity.plan_limits is on for it.
        loopback_routes=(
            "POST /v1/profile/registrations",
            "POST /v1/businesses",
            "POST /v1/businesses/{business_id}/registrations",
        ),
        # The engine, obligation and qa read a node, its snapshot and a business, which call
        # nothing.
        called_routes=(
            "GET /v1/profile/nodes/{node_id}",
            "GET /v1/profile/nodes/{node_id}/snapshot",
            "GET /v1/businesses/{business_id}",
        ),
        takes_token_source=True,
        calls_identity=True,
    ),
    ServiceEntry(
        "rulebook", "rulebook", RulebookSettings, build_rulebook, components=rulebook_components
    ),
    ServiceEntry(
        "applicability-engine",
        "applicability",
        ApplicabilityEngineSettings,
        build_applicability_engine,
        components=applicability_engine_components,
        url_fields=("profile_url", "rulebook_url"),
        # Evaluating reads the rule version and the profile; a dry run reads the version and
        # every profile of its scope.
        loopback_routes=(
            "POST /v1/applicability-engine/businesses/{business_id}/decisions",
            "POST /v1/applicability-engine/dry-runs",
        ),
        takes_token_source=True,
    ),
    ServiceEntry(
        "obligation",
        "obligation",
        ObligationSettings,
        build_obligation,
        components=obligation_components,
        url_fields=("rulebook_url", "profile_url"),
        # The detail reads the rulebook when its cache lacks the rule version, an assignment by
        # a verified caller asks identity whether the assignee belongs to the tenant, and the
        # public list asks profile whether a business with an empty page is the tenant's.
        loopback_routes=(
            "GET /v1/obligation/obligations/{obligation_id}",
            "PUT /v1/obligation/obligations/{obligation_id}/assignee",
            "GET /v1/obligations/{obligation_id}",
            "PUT /v1/obligations/{obligation_id}/assignee",
            "GET /v1/businesses/{business_id}/obligations",
        ),
        # qa's ask and notification's bulk read a business's obligations, which calls nothing.
        called_routes=("GET /v1/obligation/obligations",),
        takes_token_source=True,
    ),
    ServiceEntry(
        "notification",
        "notification",
        NotificationSettings,
        build_notification,
        components=notification_components,
        url_fields=("rulebook_url", "obligation_url"),
        # A CA firm's bulk notification reads each client's open obligations of the change.
        loopback_routes=("POST /v1/notification/bulk",),
        takes_token_source=True,
    ),
    ServiceEntry(
        "qa",
        "qa",
        QaSettings,
        build_qa,
        url_fields=("rulebook_url", "profile_url", "obligation_url", "llm_gateway_url"),
        # A question reads the profile, the business's obligations and the rulebook and calls
        # the gateway, under the service's prefix and as the public API's ask.
        loopback_routes=("POST /v1/qa/ask", "POST /v1/qa"),
        takes_token_source=True,
    ),
    ServiceEntry("llm-gateway", "llm_gateway", GatewaySettings, build_llm_gateway),
    ServiceEntry("eval", "eval", EvalSettings, build_eval),
    ServiceEntry(
        "pipeline",
        "pipeline",
        PipelineSettings,
        build_pipeline,
        components=pipeline_components,
        url_fields=("rulebook_url", "llm_gateway_url"),
    ),
)


def entry_named(name: str, registry: Sequence[ServiceEntry[Any]] = REGISTRY) -> ServiceEntry[Any]:
    for entry in registry:
        if entry.name == name:
            return entry
    raise KeyError(f"no service named {name!r} is registered")


def service_settings[S: Settings](
    entry: ServiceEntry[S], root: Settings, *, internal_url: str, **overrides: Any
) -> S:
    """``entry``'s settings: the root's shared settings, the service's name, its schema and a
    database URL whose ``search_path`` starts with it, every URL of another service (identity's
    and its key set's included) at ``internal_url``, then ``overrides``. The service's own
    ``CW_*`` settings come from the environment and the ``.env`` files the root read."""
    base = internal_url.rstrip("/")
    values: dict[str, Any] = {
        name: getattr(root, name)
        for name in Settings.model_fields
        if name not in SHARED_FIELDS_SET_PER_SERVICE
    }
    values.update(
        service_name=entry.name,
        database_url=with_search_path(root.database_url, entry.schema),
        db_schema=entry.schema,
        identity_url=base,
        auth_jwks_url=base + JWKS_PATH,
    )
    values.update(dict.fromkeys(entry.url_fields, base))
    values.update(overrides)
    env_files = list(root.env_files) or None
    return entry.settings_type(_env_file=env_files, **values)


def schemas(registry: Sequence[ServiceEntry[Any]] = REGISTRY) -> tuple[str, ...]:
    return tuple(entry.schema for entry in registry)


def check_overrides(
    overrides: Mapping[str, object], registry: Sequence[ServiceEntry[Any]] = REGISTRY
) -> None:
    """Raise on overrides for a service the registry does not have: a misspelt name would be
    ignored silently otherwise."""
    unknown = sorted(set(overrides) - {entry.name for entry in registry})
    if unknown:
        raise KeyError(f"overrides name services that are not registered: {unknown}")
