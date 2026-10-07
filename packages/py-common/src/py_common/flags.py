"""Feature flags from the registry (``packages/flags/registry.json``) through OpenFeature.

py-common loads its generated copy of the registry, ``flags_registry.json`` (``make flags``).
``configure_flags(settings)`` installs the provider ``CW_FLAGS_PROVIDER`` names:

- ``env`` (the default): ``EnvFlagProvider``. A flag's value comes from the variable the code
  already reads (the entry's ``env``), else from ``CW_FLAG_<NAME>`` (the name upper-cased, dots
  as underscores), else the registry default. The environment beats ``.env``, as in the settings,
  and settings built with ``_env_file=None`` read no ``.env`` for their flags either.
  A tenant-targeted flag that is on applies to the tenants in its allow-list, the entry's
  ``tenants_env`` or ``CW_FLAG_<NAME>__TENANTS`` (comma-separated tenant ids); with no list it
  applies to every tenant.
- ``unleash``: ``UnleashFlagProvider`` over the Unleash client from the optional extra
  ``py-common[unleash]``, at ``CW_UNLEASH_URL`` with the client token ``CW_UNLEASH_API_TOKEN``.
  The flag's registry name is its Unleash name and the tenant id is the targeting key (Unleash's
  ``userId``, and the ``tenantId`` property for constraints).

``flag_enabled(name, tenant_id)`` answers a bool flag and ``flag_value(name, tenant_id)`` a
string flag. A name the registry does not hold raises ``UnknownFlagError`` (flag-unknown), a
server-side defect, so every service maps it to 500. A provider error, such as a malformed value
or a flag Unleash does not know, answers the registry default, which is off, and is logged.
Until ``configure_flags`` runs, every flag answers its default.
"""

import json
import os
from collections import ChainMap
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from dotenv import dotenv_values
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from openfeature.exception import FlagNotFoundError, ParseError, TypeMismatchError
from openfeature.flag_evaluation import (
    FlagEvaluationDetails,
    FlagResolutionDetails,
    FlagValueType,
    Reason,
)
from openfeature.provider import AbstractProvider, FeatureProvider, Metadata
from openfeature.provider.no_op_provider import NoOpProvider

from domain_kernel.errors import DomainError
from py_common.logging import get_logger
from py_common.settings import Settings

REGISTRY_PATH = Path(__file__).with_name("flags_registry.json")
OVERRIDE_PREFIX = "CW_FLAG_"
TENANTS_SUFFIX = "__TENANTS"
# The OpenFeature domain py-common's provider is bound to, so another library's provider on the
# default domain is left alone.
DOMAIN = "compliancewatch"
_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})
FlagType = Literal["bool", "string"]
Targeting = Literal["none", "tenant"]

log = get_logger(__name__)


class UnknownFlagError(DomainError, LookupError):
    """The code asked for a flag that ``packages/flags/registry.json`` does not hold."""

    type_slug = "flag-unknown"
    title = "Feature flag is not registered"

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"no flag named {name!r} in packages/flags/registry.json")


@dataclass(frozen=True, slots=True)
class FlagDefinition:
    """One registry entry, as py-common evaluates it."""

    name: str
    type: FlagType
    default: bool | str
    owner: str
    targeting: Targeting
    expires: date
    removal: str
    env: str | None = None
    tenants_env: str | None = None
    values: tuple[str, ...] = ()

    @property
    def override_env(self) -> str:
        """``CW_FLAG_<NAME>``: sets the flag by its registry name."""
        return OVERRIDE_PREFIX + self.name.upper().replace(".", "_")

    @property
    def tenants_override_env(self) -> str:
        return self.override_env + TENANTS_SUFFIX

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FlagDefinition":
        kind = data["type"]
        if kind not in ("bool", "string"):
            raise ValueError(f"flag {data.get('name')!r} has unknown type {kind!r}")
        targeting = data["targeting"]
        if targeting not in ("none", "tenant"):
            raise ValueError(f"flag {data.get('name')!r} has unknown targeting {targeting!r}")
        return cls(
            name=str(data["name"]),
            type=kind,
            default=data["default"],
            owner=str(data["owner"]),
            targeting=targeting,
            expires=date.fromisoformat(data["expires"]),
            removal=str(data["removal"]),
            env=data.get("env"),
            tenants_env=data.get("tenants_env"),
            values=tuple(data.get("values", ())),
        )


@dataclass(frozen=True, slots=True)
class FlagRegistry:
    """The registered flags by name."""

    flags: Mapping[str, FlagDefinition]

    def get(self, name: str) -> FlagDefinition:
        definition = self.flags.get(name)
        if definition is None:
            raise UnknownFlagError(name)
        return definition

    def __iter__(self) -> Iterator[FlagDefinition]:
        return iter(self.flags.values())

    def __len__(self) -> int:
        return len(self.flags)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FlagRegistry":
        definitions = [FlagDefinition.from_mapping(entry) for entry in data["flags"]]
        return cls({definition.name: definition for definition in definitions})

    @classmethod
    def load(cls, path: Path = REGISTRY_PATH) -> "FlagRegistry":
        return cls.from_mapping(json.loads(path.read_text(encoding="utf-8")))


@cache
def default_registry() -> FlagRegistry:
    """The registry py-common ships (``flags_registry.json``), read once."""
    return FlagRegistry.load()


def _canonical_tenant(value: str) -> str:
    try:
        return str(UUID(value.strip()))
    except ValueError as error:
        raise ParseError(f"{value.strip()!r} is not a tenant id") from error


def _tenant_key(context: EvaluationContext | None) -> str | None:
    key = context.targeting_key if context is not None else None
    return _canonical_tenant(key) if key else None


class _RegistryProvider(AbstractProvider):
    """What both providers share: the registry lookup and the unsupported flag types."""

    def __init__(self, registry: FlagRegistry | None = None) -> None:
        super().__init__()
        self._registry = registry or default_registry()

    def _definition(self, flag_key: str, kind: FlagType) -> FlagDefinition:
        definition = self._registry.flags.get(flag_key)
        if definition is None:
            raise FlagNotFoundError(f"no flag named {flag_key!r} in the registry")
        if definition.type != kind:
            raise TypeMismatchError(f"{flag_key} is a {definition.type} flag, not a {kind} flag")
        return definition

    def resolve_integer_details(
        self, flag_key: str, default_value: int, evaluation_context: EvaluationContext | None = None
    ) -> FlagResolutionDetails[int]:
        raise TypeMismatchError("registry flags are bool or string")

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[float]:
        raise TypeMismatchError("registry flags are bool or string")

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Sequence[FlagValueType] | Mapping[str, FlagValueType],
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[Sequence[FlagValueType] | Mapping[str, FlagValueType]]:
        raise TypeMismatchError("registry flags are bool or string")


class EnvFlagProvider(_RegistryProvider):
    """Flags from environment variables, with a tenant allow-list per targeted flag."""

    def __init__(
        self, registry: FlagRegistry | None = None, environ: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(registry)
        self._environ: Mapping[str, str] = os.environ if environ is None else environ

    def get_metadata(self) -> Metadata:
        return Metadata(name="env")

    def _raw(self, definition: FlagDefinition) -> tuple[str, str] | None:
        """The variable that sets the flag and its value: the legacy variable first."""
        for variable in (definition.env, definition.override_env):
            if variable and self._environ.get(variable, "").strip():
                return variable, self._environ[variable].strip()
        return None

    def _allow_list(self, definition: FlagDefinition) -> frozenset[str]:
        for variable in (definition.tenants_env, definition.tenants_override_env):
            raw = self._environ.get(variable, "") if variable else ""
            if raw.strip():
                return frozenset(_canonical_tenant(part) for part in raw.split(",") if part.strip())
        return frozenset()

    def may_be_on(self, flag_key: str) -> bool:
        """Whether the bool flag is on for any tenant: its variable says true, or it is unset and
        the default is on."""
        definition = self._definition(flag_key, "bool")
        raw = self._raw(definition)
        return bool(definition.default) if raw is None else raw[1].lower() in _TRUE

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[bool]:
        definition = self._definition(flag_key, "bool")
        raw = self._raw(definition)
        if raw is None:
            return FlagResolutionDetails(value=bool(definition.default), reason=Reason.DEFAULT)
        variable, text = raw
        if text.lower() not in _TRUE | _FALSE:
            raise ParseError(f"{variable}={text!r} is not true or false")
        if text.lower() in _FALSE:
            return FlagResolutionDetails(value=False, reason=Reason.STATIC)
        allowed = self._allow_list(definition) if definition.targeting == "tenant" else frozenset()
        if not allowed:
            return FlagResolutionDetails(value=True, reason=Reason.STATIC)
        tenant = _tenant_key(evaluation_context)
        return FlagResolutionDetails(
            value=tenant in allowed,
            reason=Reason.TARGETING_MATCH if tenant in allowed else Reason.DEFAULT,
        )

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[str]:
        definition = self._definition(flag_key, "string")
        raw = self._raw(definition)
        if raw is None:
            return FlagResolutionDetails(value=str(definition.default), reason=Reason.DEFAULT)
        variable, text = raw
        if text not in definition.values:
            raise ParseError(f"{variable}={text!r} is not one of {list(definition.values)}")
        return FlagResolutionDetails(value=text, reason=Reason.STATIC)


class UnleashClientLike(Protocol):
    """The part of ``UnleashClient.UnleashClient`` the provider uses."""

    def initialize_client(self, fetch_toggles: bool = True) -> None: ...

    def destroy(self) -> None: ...

    def is_enabled(
        self,
        feature_name: str,
        context: dict[str, Any] | None = None,
        fallback_function: Callable[..., bool] | None = None,
    ) -> bool: ...

    def get_variant(
        self, feature_name: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class UnleashFlagProvider(_RegistryProvider):
    """Flags from an Unleash server. The client polls it in the background; an evaluation reads
    the client's last copy and makes no request."""

    def __init__(self, client: UnleashClientLike, registry: FlagRegistry | None = None) -> None:
        super().__init__(registry)
        self._client = client

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        registry: FlagRegistry | None = None,
        *,
        cache_directory: str | None = None,
    ) -> "UnleashFlagProvider":
        """A provider over a real client for ``CW_UNLEASH_URL`` (``py-common[unleash]``). The
        client keeps its last copy of the flags in ``cache_directory`` (the user cache directory
        when None) and starts from it when Unleash cannot be reached."""
        if not settings.unleash_url or settings.unleash_api_token is None:
            raise ValueError(
                "CW_FLAGS_PROVIDER=unleash needs CW_UNLEASH_URL and CW_UNLEASH_API_TOKEN"
            )
        try:
            # Imported here: the client is the optional extra, needed only with this provider.
            from UnleashClient import UnleashClient
        except ImportError as error:
            raise RuntimeError(
                "CW_FLAGS_PROVIDER=unleash needs the Unleash client: install py-common[unleash]"
            ) from error
        client = UnleashClient(
            url=settings.unleash_url,
            app_name=f"compliancewatch-{settings.service_name}",
            custom_headers={"Authorization": settings.unleash_api_token.get_secret_value()},
            cache_directory=cache_directory,
        )
        return cls(cast(UnleashClientLike, client), registry)

    def get_metadata(self) -> Metadata:
        return Metadata(name="unleash")

    def initialize(self, evaluation_context: EvaluationContext) -> None:
        self._client.initialize_client()

    def shutdown(self) -> None:
        self._client.destroy()

    @staticmethod
    def _context(evaluation_context: EvaluationContext | None) -> dict[str, Any]:
        tenant = _tenant_key(evaluation_context)
        if tenant is None:
            return {}
        return {"userId": tenant, "properties": {"tenantId": tenant}}

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[bool]:
        definition = self._definition(flag_key, "bool")
        known = True

        def fallback(_name: str, _context: object) -> bool:
            nonlocal known
            known = False
            return bool(definition.default)

        context = self._context(evaluation_context)
        value = self._client.is_enabled(flag_key, context, fallback_function=fallback)
        if not known:
            raise FlagNotFoundError(f"Unleash has no flag named {flag_key!r}")
        reason = Reason.TARGETING_MATCH if context else Reason.STATIC
        return FlagResolutionDetails(value=bool(value), reason=reason)

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[str]:
        """A string flag is an Unleash variant: the payload's value, else the variant's name."""
        definition = self._definition(flag_key, "string")
        variant = self._client.get_variant(flag_key, self._context(evaluation_context))
        if not variant.get("enabled"):
            return FlagResolutionDetails(value=str(definition.default), reason=Reason.DISABLED)
        payload = variant.get("payload") or {}
        value = payload.get("value") if payload.get("type") == "string" else variant.get("name")
        if value not in definition.values:
            raise ParseError(f"Unleash variant {value!r} is not one of {list(definition.values)}")
        return FlagResolutionDetails(
            value=str(value), variant=variant.get("name"), reason=Reason.SPLIT
        )


# ---------------------------------------------------------------- the process-wide flags


@dataclass
class _State:
    registry: FlagRegistry | None = None


_state = _State()


def environment(settings: Settings) -> Mapping[str, str]:
    """The process environment over the ``.env`` files the settings were read from, as
    pydantic-settings reads them: a variable in the environment beats the files, and a later
    file beats an earlier one. Settings built with ``_env_file=None`` read no file here either."""
    values: dict[str, str] = {}
    for env_file in settings.env_files:
        if env_file.is_file():
            values.update(
                (key, value) for key, value in dotenv_values(env_file).items() if value is not None
            )
    return ChainMap(os.environ, values)


def configure_flags(
    settings: Settings,
    *,
    registry: FlagRegistry | None = None,
    environ: Mapping[str, str] | None = None,
    unleash_client: UnleashClientLike | None = None,
) -> FeatureProvider:
    """Install the provider the settings name and wait until it is ready. ``environ`` replaces
    the environment and ``.env`` for the env provider, ``unleash_client`` the real client for
    the Unleash provider (tests)."""
    chosen = registry or default_registry()
    provider: FeatureProvider
    if settings.flags_provider == "unleash":
        provider = (
            UnleashFlagProvider(unleash_client, chosen)
            if unleash_client is not None
            else UnleashFlagProvider.from_settings(settings, chosen)
        )
    else:
        provider = EnvFlagProvider(chosen, environment(settings) if environ is None else environ)
    api.set_provider_and_wait(provider, DOMAIN)
    _state.registry = chosen
    log.info("flags_configured", provider=provider.get_metadata().name, flags=len(chosen))
    return provider


def flag_may_be_on(
    name: str, settings: Settings, *, environ: Mapping[str, str] | None = None
) -> bool:
    """Whether the bool flag ``name`` can be on for some tenant of a process with ``settings``,
    for wiring decided at startup: with Unleash always (it can turn on at any time), with the env
    provider when its variable says true (for every tenant or for the listed ones)."""
    if settings.flags_provider == "unleash":
        return True
    provider = EnvFlagProvider(
        default_registry(), environment(settings) if environ is None else environ
    )
    return provider.may_be_on(name)


def reset_flags() -> None:
    """Back to no provider: every flag answers its default (tests)."""
    api.set_provider_and_wait(NoOpProvider(), DOMAIN)
    _state.registry = None


def _registry() -> FlagRegistry:
    return _state.registry or default_registry()


def _evaluation_context(tenant_id: UUID | str | None) -> EvaluationContext:
    return EvaluationContext(targeting_key=str(tenant_id)) if tenant_id else EvaluationContext()


def _answer[T](details: FlagEvaluationDetails[T]) -> T:
    if details.error_code is not None:
        log.warning(
            "flag_evaluation_failed",
            flag=details.flag_key,
            error_code=str(details.error_code),
            error=details.error_message,
            value=details.value,
        )
    return details.value


def flag_enabled(name: str, tenant_id: UUID | str | None = None) -> bool:
    """Whether the bool flag ``name`` is on, for ``tenant_id`` when the flag targets tenants."""
    definition = _registry().get(name)
    if definition.type != "bool":
        raise TypeError(f"{name} is a string flag; read it with flag_value")
    client = api.get_client(DOMAIN)
    return _answer(
        client.get_boolean_details(name, bool(definition.default), _evaluation_context(tenant_id))
    )


def flag_value(name: str, tenant_id: UUID | str | None = None) -> str:
    """The value of the string flag ``name``, one of its registered values."""
    definition = _registry().get(name)
    if definition.type != "string":
        raise TypeError(f"{name} is a bool flag; read it with flag_enabled")
    client = api.get_client(DOMAIN)
    return _answer(
        client.get_string_details(name, str(definition.default), _evaluation_context(tenant_id))
    )


__all__ = [
    "DOMAIN",
    "OVERRIDE_PREFIX",
    "REGISTRY_PATH",
    "TENANTS_SUFFIX",
    "EnvFlagProvider",
    "FlagDefinition",
    "FlagRegistry",
    "UnknownFlagError",
    "UnleashClientLike",
    "UnleashFlagProvider",
    "configure_flags",
    "default_registry",
    "environment",
    "flag_enabled",
    "flag_may_be_on",
    "flag_value",
    "reset_flags",
]
