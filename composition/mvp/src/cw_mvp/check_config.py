"""``cw-mvp check-config``: is this environment fit for its ``CW_ENV``?

It builds the settings the way the app and the worker do (``MvpSettings``, then every
registered service's own through ``registry.service_settings``), so each rule a settings class
holds is checked by that class and reported in its words:

- py-common's: production takes ``CW_AUTH_MODE=token`` only, Kafka's SASL credentials, Temporal's
  certificate with its key, the Unleash connection, the OTel headers;
- identity's: production refuses the ``fake`` sign-in provider, ``supabase`` needs its URL and
  key, staging and production need ``CW_IDENTITY_SIGNING_KEYS``, the dev clients' secret is for
  local and test;
- the profile's (the ``http`` GSTIN lookup's URL and key), the rulebook's (the seed loaded at
  start is for local and test, on the memory store), the notification service's (the ``sink``
  channel is for local and test) and the gateway's (the ``vercel`` provider's key).

A settings class stops at its first refusal, so fixing one may bring the next to light.

In staging and production (``CW_ENV`` staging or prod) it then refuses what no class refuses
there:

- ``header`` mode in staging (staging runs ``dual``, then ``token``, before production);
- fake providers: the gateway's ``fake`` model, identity's ``fake`` sign-in in staging
  (production's is identity's own rule), the profile's ``static`` demo GSTIN table and identity's
  ``memory`` billing;
- memory stores: any ``CW_<SERVICE>_STORE=memory`` and the gateway's ``CW_LLM_LEDGER=memory``;
- synthetic approvals: a rulebook that would accept them (``synthetic_approvals_allowed``);
- placeholder secrets: ``local-write-token``, ``local-review-token`` or a ``dev-only`` value in
  any secret setting;
- secrets an enabled feature needs: WhatsApp's number id and token, email's SMTP host, sender,
  password (with a username) and feedback token, Razorpay's keys, the rulebook's review token
  for publishing and its write token for the pipeline outside token mode, and the worker's
  service client secret in token mode;
- a raw store other than S3 while the pipeline fetches documents (``fetch_switches``: the
  worker's Temporal switch, the crawl flag): the files of a local or memory raw store go with
  the machine or the process;
- the pipeline's rule extraction without its knowledge flag: the extraction reads the documents
  the rulebook keeps, so without registration nothing would be extracted.

It never prints a secret's value.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from pydantic import SecretStr, ValidationError

from cw_mvp.registry import REGISTRY, ServiceEntry, service_settings
from cw_mvp.settings import APP_SERVICE_NAME, MvpSettings
from identity.settings import IdentitySettings
from llm_gateway.settings import GatewaySettings
from notification.settings import NotificationSettings
from pipeline.settings import PipelineSettings
from profile_service.settings import ProfileSettings
from py_common.settings import Settings
from rulebook.settings import RulebookSettings

LOCAL_ENVIRONMENTS: Final = frozenset({"local", "test"})
"""Where the local conveniences are allowed; staging and prod are checked further."""
SHARED: Final = "shared"
"""Where a problem of the settings every service shares is reported."""
PLACEHOLDERS: Final = frozenset({"local-write-token", "local-review-token"})
"""The rulebook tokens make product and make web-stack pass on the dev stack (not secrets)."""
DEV_ONLY: Final = "dev-only"
"""What the dev stack's other placeholder secrets contain."""
SHARED_TOKEN_MODES: Final = frozenset({"header", "dual"})
"""The modes in which the rulebook's shared tokens open its routes."""
MEMORY: Final = "memory"
VALUE_ERROR: Final = "Value error, "


@dataclass(frozen=True, slots=True)
class Problem:
    where: str
    message: str

    def line(self) -> str:
        return f"  {self.where}: {self.message}"


@dataclass(frozen=True, slots=True)
class ConfigReport:
    env: str | None
    """The ``CW_ENV`` checked; None when the shared settings could not be read at all."""
    services: int
    problems: tuple[Problem, ...]

    @property
    def ok(self) -> bool:
        return not self.problems

    def lines(self) -> list[str]:
        target = f"CW_ENV={self.env}" if self.env else "the shared settings"
        if self.ok:
            return [f"check-config: {target}, {self.services} services: no problems"]
        count = len(self.problems)
        head = f"check-config: {target}: {count} problem{'s' if count != 1 else ''}"
        return [head, *(problem.line() for problem in self.problems)]


def variable(field: str) -> str:
    """The environment variable of a settings field: ``llm_provider`` is ``CW_LLM_PROVIDER``."""
    return f"CW_{field.upper()}"


def refusals(where: str, error: ValidationError) -> list[Problem]:
    """A settings class's refusal, one problem per error, naming the variable of a field."""
    found: list[Problem] = []
    for item in error.errors(include_url=False):
        message = str(item["msg"]).removeprefix(VALUE_ERROR)
        location = "__".join(str(part) for part in item["loc"])
        found.append(Problem(where, f"{variable(location)}: {message}" if location else message))
    return found


def check(
    values: Mapping[str, Any] | None = None, *, registry: Sequence[ServiceEntry[Any]] = REGISTRY
) -> ConfigReport:
    """Check the environment (and the ``.env`` the settings read); ``values`` are explicit
    ``MvpSettings`` values, which win over it (tests pass ``_env_file=None``)."""
    given = {"service_name": APP_SERVICE_NAME, **(values or {})}
    problems: list[Problem] = []
    try:
        root = MvpSettings(**given)
    except ValidationError as error:
        problems += refusals(SHARED, error)
        try:
            # Production's one rule about the mode is reported above; with it met, the rest of
            # the shared settings can still be read for the services' checks.
            root = MvpSettings(**{**given, "auth_mode": "token"})
        except ValidationError:
            return ConfigReport(None, len(registry), tuple(problems))
    built: dict[str, Settings] = {}
    for entry in registry:
        url = root.mvp_internal_url
        try:
            built[entry.name] = service_settings(entry, root, internal_url=url)
        except ValidationError as error:
            problems += refusals(entry.name, error)
            try:
                lenient = service_settings(entry, root, internal_url=url, env="local")
            except ValidationError:
                continue
            # Read as local only to get past the refusal reported above; the rules below see
            # the environment's own CW_ENV.
            built[entry.name] = lenient.model_copy(update={"env": root.env})
    if root.env not in LOCAL_ENVIRONMENTS:
        problems += deployed(root, built, registry)
    return ConfigReport(root.env, len(registry), tuple(_unique(problems)))


def _unique(problems: Sequence[Problem]) -> list[Problem]:
    seen: set[str] = set()
    kept: list[Problem] = []
    for problem in problems:
        if problem.message not in seen:
            seen.add(problem.message)
            kept.append(problem)
    return kept


def deployed(
    root: MvpSettings, built: Mapping[str, Settings], registry: Sequence[ServiceEntry[Any]]
) -> list[Problem]:
    """The staging and production rules no settings class holds."""
    found = [Problem(SHARED, message) for message in _shared(root)]
    found += _placeholders(root, built)
    for entry in registry:
        settings = built.get(entry.name)
        if settings is not None:
            found += [Problem(entry.name, message) for message in _service(entry, settings, root)]
    return found


def _shared(root: MvpSettings) -> Iterator[str]:
    if root.env == "staging" and root.auth_mode not in ("dual", "token"):
        yield (
            f"CW_ENV=staging needs CW_AUTH_MODE dual or token, got {root.auth_mode}: staging "
            "proves the access tokens before production, which takes token only"
        )
    worker_calls = root.worker_kafka_enabled or root.worker_temporal_enabled
    if root.auth_mode == "token" and worker_calls and not _set(root.service_client_secret):
        yield (
            "CW_AUTH_MODE=token with the worker's Kafka or Temporal switch on needs "
            "CW_SERVICE_CLIENT_SECRET: the worker calls the services with its own service "
            "client's tokens, and token mode refuses a call without one"
        )


def _service(entry: ServiceEntry[Any], settings: Settings, root: MvpSettings) -> Iterator[str]:
    env = settings.env
    store = entry.store_field
    if store is not None and getattr(settings, store) == MEMORY:
        yield (
            f"{variable(store)}=memory keeps the service's state in one process and loses it "
            f"on a restart; CW_ENV={env} needs postgres"
        )
    if getattr(settings, "synthetic_approvals_allowed", False):
        yield (
            f"the rulebook accepts synthetic approvals with CW_ENV={env}; only local and test "
            "may, where the demo publication sends them"
        )
    if isinstance(settings, IdentitySettings):
        yield from _identity(settings)
    elif isinstance(settings, ProfileSettings):
        yield from _profile(settings)
    elif isinstance(settings, RulebookSettings):
        yield from _rulebook(settings)
    elif isinstance(settings, NotificationSettings):
        yield from _notification(settings)
    elif isinstance(settings, GatewaySettings):
        yield from _gateway(settings)
    elif isinstance(settings, PipelineSettings):
        yield from _pipeline(settings, root)


def _profile(settings: ProfileSettings) -> Iterator[str]:
    if settings.profile_gstin_lookup == "static":
        yield (
            "CW_PROFILE_GSTIN_LOOKUP=static pre-fills from the demo table; CW_ENV="
            f"{settings.env} needs manual, or http once the provider is signed"
        )


def _rulebook(settings: RulebookSettings) -> Iterator[str]:
    shared_tokens = settings.auth_mode in SHARED_TOKEN_MODES
    missing = _unset(settings, "rulebook_review_token")
    if settings.rulebook_publish_enabled and shared_tokens and missing:
        yield (
            f"CW_RULEBOOK_PUBLISH_ENABLED in {settings.auth_mode} mode needs "
            f"{', '.join(missing)}: the analysts' actions are refused without it"
        )


def _gateway(settings: GatewaySettings) -> Iterator[str]:
    if settings.llm_provider == "fake":
        yield (
            f"CW_LLM_PROVIDER=fake answers from a fake model; CW_ENV={settings.env} needs "
            "vercel with CW_AI_GATEWAY_API_KEY"
        )
    if settings.llm_ledger == MEMORY:
        yield (
            "CW_LLM_LEDGER=memory forgets the spend on a restart, and the budgets with it; "
            f"CW_ENV={settings.env} needs postgres"
        )


def fetch_switches(root: MvpSettings, settings: PipelineSettings) -> tuple[str, ...]:
    """The switches that are on and have the pipeline fetch regulator documents and keep their
    files: the worker's Temporal switch runs the pipeline's fetch activities, and the crawl flag
    has the worker's tick and an admin's fetch start crawls of the regulator sites."""
    switches: list[str] = []
    if root.worker_temporal_enabled:
        switches.append("CW_WORKER_TEMPORAL_ENABLED")
    if settings.pipeline_crawl_enabled:
        switches.append("CW_PIPELINE_CRAWL_ENABLED")
    return tuple(switches)


def _pipeline(settings: PipelineSettings, root: MvpSettings) -> Iterator[str]:
    shared_tokens = settings.auth_mode in SHARED_TOKEN_MODES
    missing = _unset(settings, "rulebook_write_token")
    if settings.pipeline_knowledge_enabled and shared_tokens and missing:
        yield (
            f"CW_PIPELINE_KNOWLEDGE_ENABLED in {settings.auth_mode} mode needs "
            f"{', '.join(missing)}: the rulebook refuses the pipeline's writes without it"
        )
    if settings.pipeline_extraction_enabled and not settings.pipeline_knowledge_enabled:
        yield (
            "CW_PIPELINE_EXTRACTION_ENABLED needs CW_PIPELINE_KNOWLEDGE_ENABLED: the extraction "
            "reads the documents the rulebook keeps, and without it none is registered"
        )
    switches = fetch_switches(root, settings)
    store = settings.pipeline_raw_store
    if switches and store != "s3":
        kept = "on one machine's disk" if store == "local" else "in one process's memory"
        yield (
            f"CW_PIPELINE_RAW_STORE={store} keeps the regulator files {kept}, which a restart "
            f"or a new machine loses; CW_ENV={settings.env} needs s3 while "
            f"{' and '.join(switches)} {'has' if len(switches) == 1 else 'have'} the worker "
            "fetch documents"
        )


def _identity(settings: IdentitySettings) -> Iterator[str]:
    if settings.auth_provider == "fake" and settings.env == "staging":
        yield (
            "CW_AUTH_PROVIDER=fake signs anyone in; CW_ENV=staging needs supabase, as "
            "production does"
        )
    if settings.billing_provider == MEMORY:
        yield (
            f"CW_BILLING_PROVIDER=memory is a fake billing provider; CW_ENV={settings.env} "
            "needs none, or razorpay once the account exists"
        )
    if settings.billing_provider == "razorpay":
        missing = _unset(
            settings, "razorpay_key_id", "razorpay_key_secret", "razorpay_webhook_secret"
        )
        if missing:
            yield (
                f"CW_BILLING_PROVIDER=razorpay needs {', '.join(missing)}: billing is off "
                "without them"
            )


def _notification(settings: NotificationSettings) -> Iterator[str]:
    if settings.whatsapp_enabled:
        missing = _unset(settings, "whatsapp_phone_number_id", "whatsapp_access_token")
        if missing:
            yield (
                f"CW_WHATSAPP_ENABLED needs {', '.join(missing)}: every WhatsApp message fails "
                "without them"
            )
    if settings.email_enabled:
        needed = ["smtp_host", "email_from", "notification_email_feedback_token"]
        if settings.smtp_username:
            needed.append("smtp_password")
        missing = _unset(settings, *needed)
        if missing:
            yield (
                f"CW_EMAIL_ENABLED needs {', '.join(missing)}: email is off without the host "
                "and sender, the login without its password, and bounces and complaints are "
                "refused without the feedback token"
            )


def _placeholders(root: MvpSettings, built: Mapping[str, Settings]) -> list[Problem]:
    """Every secret setting that holds a dev stack placeholder, once per variable."""
    found: dict[str, Problem] = {}
    holders: list[tuple[str, Settings]] = [(SHARED, root), *built.items()]
    for where, settings in holders:
        for field in type(settings).model_fields:
            value = getattr(settings, field)
            if not isinstance(value, SecretStr) or variable(field) in found:
                continue
            text = value.get_secret_value()
            scope = SHARED if field in Settings.model_fields else where
            if text in PLACEHOLDERS:
                found[variable(field)] = Problem(
                    scope,
                    f"{variable(field)} is the placeholder {text}, which the dev stack uses; "
                    f"CW_ENV={root.env} needs its own secret",
                )
            elif DEV_ONLY in text.lower():
                found[variable(field)] = Problem(
                    scope,
                    f"{variable(field)} holds a dev-only placeholder; CW_ENV={root.env} needs its "
                    "own secret",
                )
    return list(found.values())


def _set(value: SecretStr | str | None) -> bool:
    text = value.get_secret_value() if isinstance(value, SecretStr) else value
    return bool(text and text.strip())


def _unset(settings: Settings, *fields: str) -> list[str]:
    return [variable(field) for field in fields if not _set(getattr(settings, field))]
