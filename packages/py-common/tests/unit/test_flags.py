"""Feature flags: the registry copy, the env provider, the Unleash provider over a fake client,
and the process-wide ``flag_enabled`` and ``flag_value``."""

import json
import os
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from openfeature.evaluation_context import EvaluationContext
from openfeature.exception import FlagNotFoundError, TypeMismatchError
from pydantic import SecretStr, ValidationError
from structlog.testing import capture_logs

from py_common import flags
from py_common.flags import (
    EnvFlagProvider,
    FlagDefinition,
    FlagRegistry,
    UnknownFlagError,
    UnleashFlagProvider,
    configure_flags,
    default_registry,
    environment,
    flag_enabled,
    flag_value,
    reset_flags,
)
from py_common.problems import DEFAULT_STATUS_BY_ERROR
from py_common.settings import Settings

TENANT_A = "3f1c2a8e-0000-4000-8000-00000000000a"
TENANT_B = "3f1c2a8e-0000-4000-8000-00000000000b"
REPOSITORY_REGISTRY = Path(__file__).resolve().parents[4] / "packages" / "flags" / "registry.json"
# Placeholder credentials for the fake Unleash client; gitleaks reads assignments like these.
UNLEASH_URL = "http://unleash.test/api"
UNLEASH_CLIENT_TOKEN = "default:development.unit-test-placeholder"


def entry(name: str, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "type": "bool",
        "default": False,
        "owner": "platform",
        "description": "A demo switch.",
        "removal": "Once the demo ships.",
        "expires": "2027-03-31",
        "targeting": "none",
        "services": ["py-common"],
    }
    base.update(fields)
    return base


REGISTRY = FlagRegistry.from_mapping(
    {
        "flags": [
            entry("demo.switch", env="CW_DEMO_ENABLED"),
            entry(
                "demo.tenanted",
                env="CW_DEMO_TENANTED_ENABLED",
                targeting="tenant",
                tenants_env="CW_DEMO_TENANTS",
            ),
            entry("demo.fresh", targeting="tenant"),
            entry(
                "demo.provider",
                type="string",
                default="none",
                values=["none", "sandbox"],
                env="CW_DEMO_PROVIDER",
            ),
        ]
    }
)


@pytest.fixture(autouse=True)
def _no_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith("CW_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)  # no repo .env in reach
    reset_flags()
    yield
    reset_flags()


def use_env(**environ: str) -> None:
    configure_flags(Settings(), registry=REGISTRY, environ=environ)


# ---------------------------------------------------------------- the registry


def test_the_packaged_copy_holds_every_registered_flag() -> None:
    source = json.loads(REPOSITORY_REGISTRY.read_text(encoding="utf-8"))
    registry = default_registry()
    assert {definition.name for definition in registry} == {
        flag["name"] for flag in source["flags"]
    }
    assert len(registry) == len(source["flags"])
    assert all(definition.default is False for definition in registry if definition.type == "bool")
    kag = registry.get("qa.kag")
    assert (kag.env, kag.tenants_env, kag.targeting) == (
        "CW_QA_KAG_ENABLED",
        "CW_QA_KAG_TENANTS",
        "tenant",
    )
    assert registry.get("flags.provider").values == ("env", "unleash")


def test_override_variables_follow_the_name() -> None:
    definition = REGISTRY.get("demo.fresh")
    assert definition.override_env == "CW_FLAG_DEMO_FRESH"
    assert definition.tenants_override_env == "CW_FLAG_DEMO_FRESH__TENANTS"


@pytest.mark.parametrize(("field", "value"), [("type", "int"), ("targeting", "region")])
def test_a_malformed_entry_is_refused(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=f"unknown {field}"):
        FlagDefinition.from_mapping(entry("demo.bad", **{field: value}))


def test_an_unknown_flag_raises_flag_unknown() -> None:
    with pytest.raises(UnknownFlagError) as caught:
        flag_enabled("demo.nowhere")
    assert caught.value.type_slug == "flag-unknown"
    assert caught.value.name == "demo.nowhere"
    assert "packages/flags/registry.json" in caught.value.detail
    assert DEFAULT_STATUS_BY_ERROR[UnknownFlagError] == 500
    with pytest.raises(UnknownFlagError):
        flag_value("demo.nowhere")


def test_every_flag_answers_its_default_before_configure() -> None:
    assert flag_enabled("qa.kag", TENANT_A) is False
    assert flag_value("flags.provider") == "env"


def test_a_flag_is_read_with_the_reader_of_its_type() -> None:
    use_env()
    with pytest.raises(TypeError, match="read it with flag_value"):
        flag_enabled("demo.provider")
    with pytest.raises(TypeError, match="read it with flag_enabled"):
        flag_value("demo.switch")


# ---------------------------------------------------------------- the env provider


def test_the_default_applies_without_a_variable() -> None:
    use_env()
    assert flag_enabled("demo.switch") is False
    assert flag_value("demo.provider") == "none"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("1", True), ("yes", True), ("ON", True), ("false", False), ("0", False)],
)
def test_the_legacy_variable_turns_a_flag_on_or_off(raw: str, expected: bool) -> None:
    use_env(CW_DEMO_ENABLED=raw)
    assert flag_enabled("demo.switch") is expected


def test_the_flag_variable_overrides_the_default() -> None:
    use_env(CW_FLAG_DEMO_SWITCH="true")
    assert flag_enabled("demo.switch") is True


def test_the_legacy_variable_beats_the_flag_variable() -> None:
    use_env(CW_DEMO_ENABLED="false", CW_FLAG_DEMO_SWITCH="true")
    assert flag_enabled("demo.switch") is False


def test_a_blank_variable_is_unset() -> None:
    use_env(CW_DEMO_ENABLED="  ", CW_FLAG_DEMO_SWITCH="true")
    assert flag_enabled("demo.switch") is True


def test_a_malformed_value_answers_the_default_and_is_logged() -> None:
    use_env(CW_DEMO_ENABLED="maybe")
    with capture_logs() as logs:
        assert flag_enabled("demo.switch") is False
    assert logs == [
        {
            "event": "flag_evaluation_failed",
            "log_level": "warning",
            "flag": "demo.switch",
            "error_code": "PARSE_ERROR",
            "error": "CW_DEMO_ENABLED='maybe' is not true or false",
            "value": False,
        }
    ]


def test_a_tenant_allow_list_narrows_a_flag_that_is_on() -> None:
    use_env(CW_DEMO_TENANTED_ENABLED="true", CW_DEMO_TENANTS=f" {TENANT_A.upper()} ,")
    assert flag_enabled("demo.tenanted", TENANT_A) is True
    assert flag_enabled("demo.tenanted", UUID(TENANT_A)) is True
    assert flag_enabled("demo.tenanted", TENANT_B) is False
    assert flag_enabled("demo.tenanted") is False


def test_the_allow_list_does_not_turn_a_flag_on() -> None:
    use_env(CW_DEMO_TENANTS=TENANT_A)
    assert flag_enabled("demo.tenanted", TENANT_A) is False


def test_a_flag_without_an_allow_list_is_on_for_every_tenant() -> None:
    use_env(CW_DEMO_TENANTED_ENABLED="true")
    assert flag_enabled("demo.tenanted", TENANT_A) is True
    assert flag_enabled("demo.tenanted", TENANT_B) is True
    assert flag_enabled("demo.tenanted") is True


def test_the_flag_variables_carry_a_new_flag_and_its_tenants() -> None:
    use_env(CW_FLAG_DEMO_FRESH="true", CW_FLAG_DEMO_FRESH__TENANTS=TENANT_B)
    assert flag_enabled("demo.fresh", TENANT_B) is True
    assert flag_enabled("demo.fresh", TENANT_A) is False


def test_an_untargeted_flag_ignores_a_tenant_list() -> None:
    use_env(CW_DEMO_ENABLED="true", CW_FLAG_DEMO_SWITCH__TENANTS=TENANT_A)
    assert flag_enabled("demo.switch", TENANT_B) is True


def test_a_malformed_tenant_answers_off() -> None:
    use_env(CW_DEMO_TENANTED_ENABLED="true", CW_DEMO_TENANTS="acme")
    with capture_logs() as logs:
        assert flag_enabled("demo.tenanted", TENANT_A) is False
    assert logs[0]["error"] == "'acme' is not a tenant id"
    use_env(CW_DEMO_TENANTED_ENABLED="true", CW_DEMO_TENANTS=TENANT_A)
    assert flag_enabled("demo.tenanted", "not-a-uuid") is False


def test_a_string_flag_takes_one_of_its_values() -> None:
    use_env(CW_DEMO_PROVIDER="sandbox")
    assert flag_value("demo.provider") == "sandbox"
    use_env(CW_DEMO_PROVIDER="http")
    with capture_logs() as logs:
        assert flag_value("demo.provider") == "none"
    assert logs[0]["error"] == "CW_DEMO_PROVIDER='http' is not one of ['none', 'sandbox']"


def test_the_provider_refuses_other_types_and_unknown_keys() -> None:
    provider = EnvFlagProvider(REGISTRY, {})
    assert provider.get_metadata().name == "env"
    with pytest.raises(FlagNotFoundError):
        provider.resolve_boolean_details("demo.nowhere", False)
    with pytest.raises(TypeMismatchError):
        provider.resolve_string_details("demo.switch", "")
    with pytest.raises(TypeMismatchError):
        provider.resolve_integer_details("demo.switch", 0)
    with pytest.raises(TypeMismatchError):
        provider.resolve_float_details("demo.switch", 0.0)
    with pytest.raises(TypeMismatchError):
        provider.resolve_object_details("demo.switch", {})


def test_configure_reads_the_environment_over_the_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(
        "CW_FLAG_DEMO_SWITCH=true\nCW_DEMO_PROVIDER=sandbox\nCW_EMPTY\n", encoding="utf-8"
    )
    configure_flags(Settings(), registry=REGISTRY)
    assert flag_enabled("demo.switch") is True
    assert flag_value("demo.provider") == "sandbox"
    monkeypatch.setenv("CW_DEMO_PROVIDER", "none")
    assert flag_value("demo.provider") == "none"


def test_the_environment_alone_without_an_env_file() -> None:
    settings = Settings()
    assert dict(environment(settings)) == dict(os.environ)


def test_settings_kept_from_the_env_file_keep_their_flags_from_it(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CW_FLAG_DEMO_SWITCH=true\n", encoding="utf-8")
    configure_flags(Settings(_env_file=None), registry=REGISTRY)
    assert flag_enabled("demo.switch") is False
    configure_flags(Settings(), registry=REGISTRY)
    assert flag_enabled("demo.switch") is True


def test_the_flags_read_the_env_files_the_settings_named(tmp_path: Path) -> None:
    (tmp_path / "base.env").write_text(
        "CW_DEMO_PROVIDER=sandbox\nCW_FLAG_DEMO_SWITCH=true\n", encoding="utf-8"
    )
    (tmp_path / "local.env").write_text("CW_DEMO_PROVIDER=none\n", encoding="utf-8")
    settings = Settings(_env_file=("base.env", "local.env", "missing.env"))
    assert settings.env_files == (Path("base.env"), Path("local.env"), Path("missing.env"))
    configure_flags(settings, registry=REGISTRY)
    assert flag_enabled("demo.switch") is True
    assert flag_value("demo.provider") == "none", "a later file wins, as in the settings"


def test_reset_returns_every_flag_to_its_default() -> None:
    use_env(CW_DEMO_ENABLED="true")
    assert flag_enabled("demo.switch") is True
    reset_flags()
    assert flag_enabled("qa.kag") is False
    with pytest.raises(UnknownFlagError):
        flag_enabled("demo.switch")  # the default registry again


# ---------------------------------------------------------------- settings


def test_the_env_provider_is_the_default() -> None:
    settings = Settings()
    assert settings.flags_provider == "env"
    assert settings.unleash_url is None
    assert settings.unleash_api_token is None


def test_unleash_needs_its_url_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_FLAGS_PROVIDER", "unleash")
    with pytest.raises(ValidationError, match="CW_UNLEASH_URL and CW_UNLEASH_API_TOKEN"):
        Settings()
    monkeypatch.setenv("CW_UNLEASH_URL", UNLEASH_URL)
    monkeypatch.setenv("CW_UNLEASH_API_TOKEN", UNLEASH_CLIENT_TOKEN)
    settings = Settings()
    assert settings.flags_provider == "unleash"
    assert settings.unleash_api_token is not None
    assert settings.unleash_api_token.get_secret_value() == UNLEASH_CLIENT_TOKEN


# ---------------------------------------------------------------- the Unleash provider


class FakeUnleash:
    """Answers like UnleashClient: a missing feature calls the fallback."""

    def __init__(
        self,
        features: dict[str, Callable[[dict[str, Any]], bool]] | None = None,
        variants: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.features = features or {}
        self.variants = variants or {}
        self.contexts: list[dict[str, Any] | None] = []
        self.initialized = False
        self.destroyed = False

    def initialize_client(self, fetch_toggles: bool = True) -> None:
        self.initialized = fetch_toggles

    def destroy(self) -> None:
        self.destroyed = True

    def is_enabled(
        self,
        feature_name: str,
        context: dict[str, Any] | None = None,
        fallback_function: Callable[..., bool] | None = None,
    ) -> bool:
        self.contexts.append(context)
        rule = self.features.get(feature_name)
        if rule is None:
            return fallback_function(feature_name, context) if fallback_function else False
        return rule(context or {})

    def get_variant(
        self, feature_name: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.contexts.append(context)
        return self.variants.get(feature_name, {"name": "disabled", "enabled": False})


def unleash_settings() -> Settings:
    return Settings(
        flags_provider="unleash",
        unleash_url=UNLEASH_URL,
        unleash_api_token=SecretStr(UNLEASH_CLIENT_TOKEN),
    )


def use_unleash(client: FakeUnleash) -> None:
    configure_flags(unleash_settings(), registry=REGISTRY, unleash_client=client)


def test_configure_initialises_the_unleash_client() -> None:
    client = FakeUnleash()
    provider = configure_flags(unleash_settings(), registry=REGISTRY, unleash_client=client)
    assert client.initialized is True
    assert provider.get_metadata().name == "unleash"
    provider.shutdown()
    assert client.destroyed is True


def test_unleash_answers_a_flag_for_the_tenant() -> None:
    client = FakeUnleash(
        {"demo.tenanted": lambda context: context.get("userId") == TENANT_A},
    )
    use_unleash(client)
    assert flag_enabled("demo.tenanted", TENANT_A.upper()) is True
    assert flag_enabled("demo.tenanted", TENANT_B) is False
    assert flag_enabled("demo.tenanted") is False
    assert client.contexts == [
        {"userId": TENANT_A, "properties": {"tenantId": TENANT_A}},
        {"userId": TENANT_B, "properties": {"tenantId": TENANT_B}},
        {},
    ]


def test_a_flag_unleash_does_not_know_answers_the_default() -> None:
    use_unleash(FakeUnleash())
    with capture_logs() as logs:
        assert flag_enabled("demo.switch") is False
    assert logs[0]["error_code"] == "FLAG_NOT_FOUND"
    assert logs[0]["error"] == "Unleash has no flag named 'demo.switch'"


def test_a_string_flag_is_an_unleash_variant() -> None:
    client = FakeUnleash(
        variants={
            "demo.provider": {
                "name": "rollout",
                "enabled": True,
                "payload": {"type": "string", "value": "sandbox"},
            }
        }
    )
    use_unleash(client)
    assert flag_value("demo.provider", TENANT_A) == "sandbox"
    client.variants["demo.provider"] = {"name": "sandbox", "enabled": True}
    assert flag_value("demo.provider") == "sandbox"
    client.variants["demo.provider"] = {"name": "disabled", "enabled": False}
    assert flag_value("demo.provider") == "none"
    client.variants["demo.provider"] = {"name": "http", "enabled": True}
    with capture_logs() as logs:
        assert flag_value("demo.provider") == "none"
    assert logs[0]["error"] == "Unleash variant 'http' is not one of ['none', 'sandbox']"


def test_the_unleash_provider_checks_the_registry_first() -> None:
    provider = UnleashFlagProvider(FakeUnleash(), REGISTRY)
    with pytest.raises(FlagNotFoundError):
        provider.resolve_boolean_details("demo.nowhere", False, EvaluationContext())
    with pytest.raises(TypeMismatchError):
        provider.resolve_boolean_details("demo.provider", False)


def test_from_settings_builds_the_real_client(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []

    def unleash_client(**options: Any) -> FakeUnleash:
        built.append(options)
        return FakeUnleash()

    module = types.ModuleType("UnleashClient")
    module.UnleashClient = unleash_client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "UnleashClient", module)
    provider = UnleashFlagProvider.from_settings(
        unleash_settings().model_copy(update={"service_name": "profile"})
    )
    assert isinstance(provider, UnleashFlagProvider)
    assert built == [
        {
            "url": UNLEASH_URL,
            "app_name": "compliancewatch-profile",
            "custom_headers": {"Authorization": UNLEASH_CLIENT_TOKEN},
            "cache_directory": None,
        }
    ]


def test_from_settings_needs_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "UnleashClient", None)
    with pytest.raises(RuntimeError, match=r"py-common\[unleash\]"):
        UnleashFlagProvider.from_settings(unleash_settings())
    with pytest.raises(RuntimeError, match=r"py-common\[unleash\]"):
        configure_flags(unleash_settings(), registry=REGISTRY)


def test_from_settings_needs_the_connection() -> None:
    settings = Settings.model_construct(flags_provider="unleash", unleash_url=None)
    with pytest.raises(ValueError, match="CW_UNLEASH_URL and CW_UNLEASH_API_TOKEN"):
        UnleashFlagProvider.from_settings(settings)


def test_the_module_exports_its_api() -> None:
    assert set(flags.__all__) >= {"configure_flags", "flag_enabled", "flag_value"}
