"""The registry names every service once, with what the app and the worker need to host it."""

import importlib
import inspect
import re
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest

from cw_mvp.exposure import EXPOSURE
from cw_mvp.registry import (
    JWKS_PATH,
    REGISTRY,
    ServiceEntry,
    check_overrides,
    entry_named,
    schemas,
    service_settings,
)
from cw_mvp.testing import MEMORY_SERVICES, mvp_settings
from py_common.settings import Settings
from qa.main import build_app as build_qa
from qa.settings import QaSettings

REPO = Path(__file__).resolve().parents[4]
SERVICES_DIR = REPO / "services"
INIT_SQL = REPO / "infra" / "dev" / "postgres" / "init.sql"
INTERNAL = "http://mvp-app:8080"
BY_NAME = {entry.name: entry for entry in REGISTRY}


def _package(service: str) -> str:
    """The import package of a service: the one directory under ``src`` with a ``main.py``."""
    (main,) = (SERVICES_DIR / service / "src").glob("*/main.py")
    return main.parent.name


def test_every_service_directory_is_registered_once_with_identity_first() -> None:
    directories = sorted(path.name for path in SERVICES_DIR.iterdir() if (path / "src").is_dir())
    names = [entry.name for entry in REGISTRY]
    assert sorted(names) == directories
    assert len(set(names)) == len(names)
    assert names[0] == "identity"


def test_the_schemas_are_the_ones_the_dev_database_creates_but_audit() -> None:
    created = re.findall(r"CREATE SCHEMA IF NOT EXISTS (\w+);", INIT_SQL.read_text("utf-8"))
    assert sorted(schemas()) == sorted(set(created) - {"audit"})


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda entry: entry.name)
def test_each_service_is_built_through_its_main_build_app(entry: ServiceEntry[Any]) -> None:
    main = importlib.import_module(f"{_package(entry.name)}.main")
    assert entry.build is main.build_app
    parameters = inspect.signature(main.build_app).parameters
    assert entry.takes_authenticator == ("authenticator" in parameters)
    assert entry.takes_token_source == ("token_source" in parameters)
    assert issubclass(entry.settings_type, Settings)


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda entry: entry.name)
def test_a_service_with_worker_components_registers_them(entry: ServiceEntry[Any]) -> None:
    package = _package(entry.name)
    if find_spec(f"{package}.worker") is None:
        assert entry.components is None
        return
    worker = importlib.import_module(f"{package}.worker")
    assert entry.components is getattr(worker, "components", None)


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda entry: entry.name)
def test_every_url_of_another_service_is_a_registered_url_field(entry: ServiceEntry[Any]) -> None:
    own = set(entry.settings_type.model_fields) - set(Settings.model_fields)
    naming_services = {
        field
        for field in own
        if field.endswith("_url") and field.removesuffix("_url").replace("_", "-") in BY_NAME
    }
    assert set(entry.url_fields) == naming_services
    assert all(called in BY_NAME for called in entry.calls)


def test_routes_that_call_other_services_go_one_level_deep() -> None:
    callers = [entry for entry in REGISTRY if entry.loopback_routes]
    assert [entry.name for entry in callers] == ["applicability-engine", "qa"]
    for entry in callers:
        assert set(entry.loopback_routes) <= set(EXPOSURE[entry.name])
        assert entry.calls, f"{entry.name} lists loopback routes but calls no service"
        for called in entry.calls:
            assert not BY_NAME[called].loopback_routes, (
                f"{called} is called by {entry.name} and makes calls of its own"
            )


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda entry: entry.name)
def test_a_store_setting_is_named_after_its_service(entry: ServiceEntry[Any]) -> None:
    own = set(entry.settings_type.model_fields) - set(Settings.model_fields)
    stores = {field for field in own if field.endswith("_store")}
    assert stores == ({entry.store_field} if entry.store_field else set())


def test_the_memory_services_put_every_store_in_memory() -> None:
    for entry in REGISTRY:
        if entry.store_field is not None:
            assert MEMORY_SERVICES[entry.name][entry.store_field] == "memory", entry.name


def test_service_settings_point_every_service_url_at_the_internal_listener() -> None:
    root = mvp_settings(database_url="postgresql+psycopg://cw:cw@db:5432/cw?sslmode=disable")
    qa = service_settings(entry_named("qa"), root, internal_url=INTERNAL + "/")
    assert isinstance(qa, QaSettings)
    assert qa.service_name == "qa"
    assert qa.db_schema == "qa"
    assert "sslmode=disable" in qa.database_url
    assert "options=-csearch_path%3Dqa%2Cpublic" in qa.database_url
    for field in ("rulebook_url", "profile_url", "obligation_url", "llm_gateway_url"):
        assert getattr(qa, field) == INTERNAL
    assert qa.identity_url == INTERNAL
    assert qa.auth_jwks_url == INTERNAL + JWKS_PATH


def test_service_settings_share_the_root_settings_and_take_overrides() -> None:
    root = mvp_settings(auth_mode="dual", kafka_bootstrap="kafka:9092", log_level="WARNING")
    rulebook = service_settings(
        entry_named("rulebook"), root, internal_url=INTERNAL, rulebook_store="memory"
    )
    assert rulebook.auth_mode == "dual"
    assert rulebook.kafka_bootstrap == "kafka:9092"
    assert rulebook.log_level == "WARNING"
    assert rulebook.rulebook_store == "memory"
    assert rulebook.env_files == ()


def test_an_entry_refuses_a_url_field_its_settings_lack() -> None:
    with pytest.raises(ValueError, match="not a URL field"):
        ServiceEntry("qa", "qa", QaSettings, build_qa, url_fields=("nowhere_url",))
    with pytest.raises(ValueError, match="not a URL field"):
        ServiceEntry("qa", "qa", QaSettings, build_qa, url_fields=("qa_kag_enabled",))


def test_lookups_refuse_unknown_services() -> None:
    with pytest.raises(KeyError, match="nowhere"):
        entry_named("nowhere")
    with pytest.raises(KeyError, match="nowhere"):
        check_overrides({"nowhere": {}})
    check_overrides({"qa": {}})
