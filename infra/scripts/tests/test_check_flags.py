"""The flag registry and the settings scan: the check behind ``make flags`` and ``flags-check``."""

import json
import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import check_flags
from check_flags import (
    NOT_FLAGS,
    SCHEMA,
    Setting,
    copy_problems,
    main,
    module_settings,
    override_env,
    problems,
    registry_problems,
    render_copy,
    scan_problems,
    settings_fields,
    write_copy,
)

TODAY = date(2026, 9, 29)
SCHEMA_DATA = json.loads(SCHEMA.read_text(encoding="utf-8"))


def entry(name: str = "demo.switch", **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "type": "bool",
        "default": False,
        "owner": "core-product",
        "description": "Turns the demo switch on.",
        "removal": "Once the demo ships.",
        "expires": "2027-03-31",
        "targeting": "none",
        "services": ["demo"],
    }
    base.update(fields)
    return base


def registry(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"$schema": "./registry.schema.json", "flags": list(entries)}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "services" / "demo").mkdir(parents=True)
    return tmp_path


def settings_module(root: Path, body: str, *, where: str = "services/demo/src/demo") -> Path:
    directory = root / where
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "settings.py"
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


def scan(root: Path, body: str, flags: dict[str, Any], **options: Any) -> list[str]:
    """The scan of one settings module; NOT_FLAGS is empty unless the test gives one."""
    settings_module(root, body)
    options.setdefault("not_flags", {})
    return scan_problems(flags, settings_fields(root), **options)


# ---------------------------------------------------------------- the repository


def test_the_repository_registry_and_settings_pass() -> None:
    assert problems() == []


def test_main_checks_the_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check"]) == 0
    assert "flags registered" in capsys.readouterr().out


def test_the_registry_holds_every_switch_on_main_with_an_owner() -> None:
    data = json.loads(check_flags.REGISTRY.read_text(encoding="utf-8"))
    by_env = {flag.get("env"): flag for flag in data["flags"]}
    for variable in (
        "CW_QA_KAG_ENABLED",
        "CW_RULEBOOK_PUBLISH_ENABLED",
        "CW_PIPELINE_KNOWLEDGE_ENABLED",
        "CW_WHATSAPP_ENABLED",
        "WHATSAPP_SEND_ENABLED",
        "WHATSAPP_CONSENT_RECORDING_ENABLED",
        "CW_BILLING_PROVIDER",
        "CW_PROFILE_GSTIN_LOOKUP",
        "CW_LLM_PROVIDER",
    ):
        assert by_env[variable]["removal"]
    assert by_env["CW_QA_KAG_ENABLED"]["tenants_env"] == "CW_QA_KAG_TENANTS"
    assert "profile.gstin_category_prefill" in {flag["name"] for flag in data["flags"]}
    assert "CW_LLM_EMBEDDING_DIMENSIONS_PARAM" not in by_env
    assert "CW_LLM_EMBEDDING_DIMENSIONS_PARAM" in NOT_FLAGS


# ---------------------------------------------------------------- the registry


def test_a_well_formed_registry_passes(root: Path) -> None:
    flags = registry(entry("demo.a"), entry("demo.b", targeting="tenant"))
    assert registry_problems(flags, SCHEMA_DATA, root=root, today=TODAY) == []


def test_a_bool_default_of_true_fails(root: Path) -> None:
    flags = registry(entry(default=True))
    assert registry_problems(flags, SCHEMA_DATA, root=root, today=TODAY) == [
        "demo.switch: a bool flag defaults to false (off), not true"
    ]


def test_an_expired_date_is_reported(root: Path) -> None:
    flags = registry(entry(expires="2026-09-28"))
    assert registry_problems(flags, SCHEMA_DATA, root=root, today=TODAY) == [
        "demo.switch: expired on 2026-09-28; remove the flag (Once the demo ships.) or have its "
        "owner, core-product, extend expires"
    ]
    assert registry_problems(flags, SCHEMA_DATA, root=root, today=date(2026, 9, 28)) == []


def test_an_unknown_owner_and_a_missing_removal_fail_the_schema(root: Path) -> None:
    bad = entry(owner="Core Product")
    del bad["removal"]
    found = registry_problems(registry(bad), SCHEMA_DATA, root=root, today=TODAY)
    assert len(found) == 2
    assert any(
        line.startswith("demo.switch: owner: 'Core Product' is not one of") for line in found
    )
    assert any("'removal' is a required property" in line for line in found)


def test_a_malformed_name_and_date_fail_the_schema(root: Path) -> None:
    found = registry_problems(
        registry(entry("NoDots", expires="31/03/2027")), SCHEMA_DATA, root=root, today=TODAY
    )
    assert any(line.startswith("NoDots: name: 'NoDots' does not match") for line in found)
    assert any(line.startswith("NoDots: expires: '31/03/2027' is not a 'date'") for line in found)


def test_a_string_flag_needs_values_that_hold_its_default(root: Path) -> None:
    missing = entry(type="string", default="off")
    found = registry_problems(registry(missing), SCHEMA_DATA, root=root, today=TODAY)
    assert found == ["demo.switch: 'values' is a required property"]
    outside = entry(type="string", default="manual", values=["static", "http"])
    assert registry_problems(registry(outside), SCHEMA_DATA, root=root, today=TODAY) == [
        "demo.switch: default \"manual\" is not one of its values ['static', 'http']"
    ]


def test_a_tenant_allow_list_needs_tenant_targeting(root: Path) -> None:
    flags = registry(entry(tenants_env="CW_DEMO_TENANTS"))
    found = registry_problems(flags, SCHEMA_DATA, root=root, today=TODAY)
    assert found == ["demo.switch: targeting: 'tenant' was expected"]


def test_duplicate_and_unsorted_names_fail(root: Path) -> None:
    flags = registry(entry("demo.b"), entry("demo.a"), entry("demo.b"))
    found = registry_problems(flags, SCHEMA_DATA, root=root, today=TODAY)
    assert "demo.b: registered 2 times; names are unique" in found
    assert any(line.startswith("registry: flags are not sorted by name") for line in found)


def test_a_variable_read_by_two_flags_fails(root: Path) -> None:
    flags = registry(entry("demo.a", env="CW_DEMO_ENABLED"), entry("demo.b", env="CW_DEMO_ENABLED"))
    assert registry_problems(flags, SCHEMA_DATA, root=root, today=TODAY) == [
        "CW_DEMO_ENABLED is read by more than one flag: demo.a, demo.b"
    ]
    clash = registry(entry("demo.a_b"), entry("demo_a.b"))
    assert registry_problems(clash, SCHEMA_DATA, root=root, today=TODAY) == [
        "CW_FLAG_DEMO_A_B is read by more than one flag: demo.a_b, demo_a.b",
        "CW_FLAG_DEMO_A_B__TENANTS is read by more than one flag: demo.a_b, demo_a.b",
    ]


def test_a_service_must_exist(root: Path) -> None:
    (root / "apps" / "bot").mkdir(parents=True)
    flags = registry(entry(services=["demo", "bot", "ghost"]))
    assert registry_problems(flags, SCHEMA_DATA, root=root, today=TODAY) == [
        "demo.switch: service ghost is not a directory under services/, apps/, packages/, "
        "composition/"
    ]


def test_override_variables_come_from_the_name() -> None:
    assert override_env("profile.gstin_category_prefill") == (
        "CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL"
    )


# ---------------------------------------------------------------- py-common's copy


def test_the_py_common_copy_drift_is_detected(tmp_path: Path) -> None:
    flags = registry(entry())
    copy = tmp_path / "flags_registry.json"
    assert copy_problems(flags, copy) == ["flags_registry.json is missing; run make flags"]
    copy.write_text(render_copy(flags), encoding="utf-8")
    assert copy_problems(flags, copy) == []
    changed = registry(entry(owner="platform"))
    assert copy_problems(changed, copy) == [
        "flags_registry.json differs from packages/flags/registry.json; run make flags and "
        "commit it"
    ]


def test_the_copy_marks_itself_generated() -> None:
    body = json.loads(render_copy(registry(entry())))
    assert body["_generated"].startswith("Generated from packages/flags/registry.json")
    assert body["flags"] == [entry()]
    assert render_copy([]) == render_copy({"flags": []})


def test_write_copy_then_check(tmp_path: Path) -> None:
    source = tmp_path / "registry.json"
    source.write_text(json.dumps(registry(entry())), encoding="utf-8")
    target = write_copy(source, tmp_path / "copy.json")
    assert json.loads(target.read_text(encoding="utf-8"))["flags"] == [entry()]


def test_main_write_regenerates_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = tmp_path / "flags_registry.json"
    monkeypatch.setattr(check_flags, "PY_COPY", copy)
    # The copy is compared with the repository registry, so a fresh one passes.
    assert main(["write"]) == 0
    assert copy.read_text(encoding="utf-8") == render_copy(
        json.loads(check_flags.REGISTRY.read_text(encoding="utf-8"))
    )
    assert "flags: wrote flags_registry.json" in capsys.readouterr().out


def test_main_reports_problems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_flags, "PY_COPY", tmp_path / "missing.json")
    assert main([]) == 1
    assert "missing.json is missing; run make flags" in capsys.readouterr().err


def test_main_write_fails_on_an_unreadable_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "registry.json"
    broken.write_text("{", encoding="utf-8")
    monkeypatch.setattr(check_flags, "REGISTRY", broken)
    assert main(["write"]) == 1
    assert "cannot read the registry" in capsys.readouterr().err
    assert problems(registry_path=broken)[0].startswith("cannot read the registry or its schema")


# ---------------------------------------------------------------- the settings scan

ENABLED_SETTINGS = """
    from pydantic_settings import BaseSettings

    class DemoSettings(BaseSettings):
        demo_enabled: bool = False
"""


def test_an_unregistered_enabled_setting_fails(root: Path) -> None:
    assert scan(root, ENABLED_SETTINGS, registry()) == [
        "services/demo/src/demo/settings.py: DemoSettings.demo_enabled (CW_DEMO_ENABLED): is a "
        'flag, but packages/flags/registry.json has no entry with "env": "CW_DEMO_ENABLED"; '
        "register it (make flags)"
    ]


def test_a_registered_enabled_setting_passes(root: Path) -> None:
    assert scan(root, ENABLED_SETTINGS, registry(entry(env="CW_DEMO_ENABLED"))) == []


def test_a_setting_that_defaults_on_fails(root: Path) -> None:
    body = ENABLED_SETTINGS.replace("= False", "= True")
    assert scan(root, body, registry(entry(env="CW_DEMO_ENABLED"))) == [
        "services/demo/src/demo/settings.py: DemoSettings.demo_enabled (CW_DEMO_ENABLED): "
        "defaults to True, but demo.switch defaults to false"
    ]


def test_a_flag_without_a_constant_default_fails(root: Path) -> None:
    body = ENABLED_SETTINGS.replace(" = False", "")
    assert scan(root, body, registry(entry(env="CW_DEMO_ENABLED"))) == [
        "services/demo/src/demo/settings.py: DemoSettings.demo_enabled (CW_DEMO_ENABLED): has no "
        "constant default; a flag is off unless set"
    ]


PROVIDER_SETTINGS = """
    from typing import Literal

    from py_common.settings import Settings

    Provider = Literal["none", "sandbox"]

    class DemoSettings(Settings):
        demo_provider: Provider = "none"
"""


def test_a_provider_switch_is_a_flag_with_its_values(root: Path) -> None:
    string = entry(type="string", default="none", values=["none", "sandbox"])
    string["env"] = "CW_DEMO_PROVIDER"
    assert scan(root, PROVIDER_SETTINGS, registry(string)) == []
    assert scan(root, PROVIDER_SETTINGS, registry()) == [
        "services/demo/src/demo/settings.py: DemoSettings.demo_provider (CW_DEMO_PROVIDER): is a "
        'flag, but packages/flags/registry.json has no entry with "env": "CW_DEMO_PROVIDER"; '
        "register it (make flags)"
    ]


def test_a_switch_that_drifts_from_its_entry_fails(root: Path) -> None:
    drifted = entry(type="string", default="sandbox", values=["none", "http"])
    drifted["env"] = "CW_DEMO_PROVIDER"
    where = "services/demo/src/demo/settings.py: DemoSettings.demo_provider (CW_DEMO_PROVIDER)"
    assert scan(root, PROVIDER_SETTINGS, registry(drifted)) == [
        f"{where}: defaults to 'none', but demo.switch defaults to \"sandbox\"",
        f"{where}: takes ['none', 'sandbox'], but demo.switch lists ['none', 'http']",
    ]
    as_bool = entry(env="CW_DEMO_PROVIDER")
    assert scan(root, PROVIDER_SETTINGS, registry(as_bool)) == [
        f"{where}: a literal setting, but demo.switch has type bool"
    ]


@pytest.mark.parametrize("suffix", ["_provider", "_mode", "_backend"])
def test_every_switch_suffix_makes_a_flag(root: Path, suffix: str) -> None:
    body = PROVIDER_SETTINGS.replace("demo_provider", f"demo{suffix}")
    found = scan(root, body, registry())
    assert len(found) == 1
    assert "is a flag, but" in found[0]


def test_a_switch_field_is_a_flag_whatever_its_name(root: Path) -> None:
    body = PROVIDER_SETTINGS.replace("demo_provider", "demo_lookup")
    assert scan(root, body, registry()) == [
        "services/demo/src/demo/settings.py: DemoSettings.demo_lookup (CW_DEMO_LOOKUP): a literal "
        "setting that is neither a registered flag nor listed in NOT_FLAGS "
        "(infra/scripts/check_flags.py); name a bool switch *_enabled and register it, or list "
        "the setting in NOT_FLAGS with the reason it is configuration"
    ]
    found = scan(root, body, registry(), switch_fields=frozenset({"demo_lookup"}))
    assert len(found) == 1
    assert "is a flag, but" in found[0]


CONFIG_SETTINGS = """
    from typing import Literal

    from py_common.settings import Settings

    class DemoSettings(Settings):
        demo_store: Literal["memory", "postgres"] = "postgres"
        demo_dimensions_param: bool = True
        demo_url: str = "http://localhost"
"""


def test_configuration_passes_when_listed_in_not_flags(root: Path) -> None:
    not_flags = {"CW_DEMO_STORE": "store selector", "CW_DEMO_DIMENSIONS_PARAM": "compatibility"}
    assert scan(root, CONFIG_SETTINGS, registry(), not_flags=not_flags) == []


def test_unlisted_configuration_fails(root: Path) -> None:
    found = scan(root, CONFIG_SETTINGS, registry())
    assert [line.split(": ")[1] for line in found] == [
        "DemoSettings.demo_store (CW_DEMO_STORE)",
        "DemoSettings.demo_dimensions_param (CW_DEMO_DIMENSIONS_PARAM)",
    ]
    assert "a literal setting that is neither a registered flag" in found[0]
    assert "a bool setting that is neither a registered flag" in found[1]


def test_not_flags_cannot_exempt_a_flag(root: Path) -> None:
    found = scan(
        root,
        ENABLED_SETTINGS,
        registry(entry(env="CW_DEMO_ENABLED")),
        not_flags={"CW_DEMO_ENABLED": "a reason"},
    )
    assert found == [
        "services/demo/src/demo/settings.py: DemoSettings.demo_enabled (CW_DEMO_ENABLED): is a "
        "flag by its name, so NOT_FLAGS cannot exempt it; register it instead"
    ]


def test_stale_and_unexplained_not_flags_entries_fail(root: Path) -> None:
    found = scan(
        root,
        CONFIG_SETTINGS,
        registry(),
        not_flags={"CW_DEMO_STORE": " ", "CW_DEMO_DIMENSIONS_PARAM": "ok", "CW_GONE": "old"},
    )
    assert found == [
        "NOT_FLAGS lists CW_DEMO_STORE without a reason",
        "NOT_FLAGS lists CW_GONE, which no settings module declares",
    ]


def test_a_registered_setting_must_be_a_bool_or_a_literal(root: Path) -> None:
    body = ENABLED_SETTINGS.replace("demo_enabled: bool = False", 'demo_url: str = "x"')
    assert scan(root, body, registry(entry(env="CW_DEMO_URL"))) == [
        "services/demo/src/demo/settings.py: DemoSettings.demo_url (CW_DEMO_URL): registered as "
        "demo.switch, but a flag is a bool or a Literal"
    ]


def test_a_tenant_allow_list_must_be_registered(root: Path) -> None:
    body = """
        from py_common.settings import Settings

        class DemoSettings(Settings):
            demo_enabled: bool = False
            demo_tenants: frozenset[str] = frozenset()
    """
    flag = entry(env="CW_DEMO_ENABLED", targeting="tenant")
    assert scan(root, body, registry(flag)) == [
        "services/demo/src/demo/settings.py: DemoSettings.demo_tenants (CW_DEMO_TENANTS): a "
        "tenant allow-list that no registry entry names as its tenants_env"
    ]
    flag["tenants_env"] = "CW_DEMO_TENANTS"
    assert scan(root, body, registry(flag)) == []


def test_the_composition_and_py_common_settings_are_scanned(root: Path) -> None:
    settings_module(root, ENABLED_SETTINGS, where="composition/mvp/src/cw_mvp")
    settings_module(
        root,
        "from pydantic_settings import BaseSettings\n\nclass Settings(BaseSettings):\n"
        "    worker_enabled: bool = False\n",
        where="packages/py-common/src/py_common",
    )
    envs = [setting.env for setting in settings_fields(root)]
    assert envs == ["CW_WORKER_ENABLED", "CW_DEMO_ENABLED"]


def test_the_scan_reads_annotations_and_defaults(root: Path) -> None:
    path = settings_module(
        root,
        """
        from typing import Annotated, ClassVar, Literal, Optional, TypeAlias

        from pydantic import Field
        from pydantic_settings import BaseSettings

        Mode: TypeAlias = Literal["a", "b"]
        type Backend = Literal["x", "y"]

        class Helper:
            helper_enabled: bool = True

        class DemoSettings(BaseSettings):
            model_config = {"env_prefix": "CW_"}
            registry: ClassVar[dict[str, str]] = {}
            one_enabled: bool | None = None
            two_enabled: Optional[bool] = Field(default=False)
            three_enabled: Annotated[bool, "note"] = Field(False, description="x")
            demo_mode: Mode = "a"
            demo_backend: Backend = Field(default_factory=lambda: "x")
            both: int | str = 1
            plain: Literal["p", "q"]
        """,
    )
    fields = {setting.name: setting for setting in module_settings(path, root)}
    assert set(fields) == {
        "one_enabled",
        "two_enabled",
        "three_enabled",
        "demo_mode",
        "demo_backend",
        "both",
        "plain",
    }
    assert [fields[name].kind for name in ("one_enabled", "two_enabled", "three_enabled")] == [
        "bool",
        "bool",
        "bool",
    ]
    assert (fields["one_enabled"].has_default, fields["one_enabled"].default) == (True, None)
    assert (fields["two_enabled"].has_default, fields["two_enabled"].default) == (True, False)
    assert fields["three_enabled"].default is False
    assert (fields["demo_mode"].kind, fields["demo_mode"].values) == ("literal", ("a", "b"))
    assert (fields["demo_backend"].values, fields["demo_backend"].has_default) == (
        ("x", "y"),
        False,
    )
    assert fields["both"].kind == "other"
    assert (fields["plain"].values, fields["plain"].has_default) == (("p", "q"), False)


def test_a_setting_names_its_variable() -> None:
    setting = Setting("a/settings.py", "DemoSettings", "demo_enabled", "bool")
    assert setting.env == "CW_DEMO_ENABLED"
    assert setting.where == "a/settings.py: DemoSettings.demo_enabled (CW_DEMO_ENABLED)"
