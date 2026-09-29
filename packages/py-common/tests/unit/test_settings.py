import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import make_url

from py_common.settings import Settings, parse_otel_headers, with_search_path

SASL_SECRET = "sasl-test-value"  # a test value, not a credential
TEMPORAL_KEY = "temporal-test-key"  # a test value, not a credential
PEM_CERT = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
PEM_KEY = "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("CW_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)  # no repo .env in reach


def test_defaults() -> None:
    settings = Settings()
    assert settings.service_name == "compliancewatch"
    assert settings.env == "local"
    assert settings.log_level == "INFO"
    assert settings.log_json is True
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.db_schema is None
    assert settings.kafka_bootstrap == "localhost:19092"
    assert settings.otel_endpoint is None
    assert settings.auth_mode == "header"
    assert settings.auth_issuer == "urn:compliancewatch:identity"
    assert settings.auth_audience == "compliancewatch"
    assert settings.auth_jwks_url == "http://localhost:8001/v1/identity/.well-known/jwks.json"
    assert settings.auth_jwks_json is None
    assert settings.auth_leeway_seconds == 30
    assert settings.identity_url == "http://localhost:8001"
    assert settings.service_client_id == ""
    assert settings.service_client_secret is None


def test_managed_connections_are_off_by_default() -> None:
    settings = Settings()
    assert settings.kafka_security_protocol == "PLAINTEXT"
    assert settings.kafka_sasl_mechanism is None
    assert settings.kafka_sasl_username is None
    assert settings.kafka_sasl_password is None
    assert settings.kafka_ssl_cafile is None
    assert settings.temporal_api_key is None
    assert settings.temporal_tls is None
    assert settings.temporal_tls_enabled is False
    assert settings.otel_protocol == "grpc"
    assert settings.otel_header_map == {}


def test_env_prefix_and_level_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_LOG_LEVEL", "debug")
    monkeypatch.setenv("CW_ENV", "prod")
    monkeypatch.setenv("CW_AUTH_MODE", "token")
    monkeypatch.setenv("CW_DB_SCHEMA", "obligation")
    settings = Settings()
    assert settings.log_level == "DEBUG"
    assert settings.env == "prod"
    assert settings.db_schema == "obligation"


def test_the_settings_remember_which_env_files_they_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CW_LOG_LEVEL=error\n", encoding="utf-8")
    assert Settings().env_files == (Path(".env"),)
    assert Settings().log_level == "ERROR"
    hermetic = Settings(_env_file=None)
    assert (hermetic.env_files, hermetic.log_level) == ((), "INFO")
    assert Settings(_env_file="other.env").env_files == (Path("other.env"),)


def test_service_name_is_passed_by_the_composition_root() -> None:
    assert Settings(service_name="obligation").service_name == "obligation"


def test_unprefixed_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "error")
    assert Settings().log_level == "INFO"


@pytest.mark.parametrize("mode", ["header", "dual"])
def test_production_refuses_every_auth_mode_but_token(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("CW_ENV", "prod")
    monkeypatch.setenv("CW_AUTH_MODE", mode)
    with pytest.raises(ValidationError, match="CW_ENV=prod needs CW_AUTH_MODE=token"):
        Settings()


def test_production_without_an_auth_mode_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_ENV", "prod")
    with pytest.raises(ValidationError, match="got header"):
        Settings()


@pytest.mark.parametrize(
    ("env", "mode"),
    [("prod", "token"), ("staging", "dual"), ("local", "header"), ("test", "token")],
)
def test_other_combinations_are_accepted(env: str, mode: str) -> None:
    settings = Settings(env=env, auth_mode=mode)  # type: ignore[arg-type]
    assert (settings.env, settings.auth_mode) == (env, mode)


@pytest.mark.parametrize("mode", ["off", "TOKEN", "bearer"])
def test_an_unknown_auth_mode_is_refused(mode: str) -> None:
    with pytest.raises(ValidationError, match="auth_mode"):
        Settings(auth_mode=mode)  # type: ignore[arg-type]


def test_leeway_is_bounded() -> None:
    with pytest.raises(ValidationError, match="auth_leeway_seconds"):
        Settings(auth_leeway_seconds=-1)
    with pytest.raises(ValidationError, match="auth_leeway_seconds"):
        Settings(auth_leeway_seconds=301)


def sasl(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "kafka_security_protocol": "SASL_SSL",
        "kafka_sasl_mechanism": "SCRAM-SHA-256",
        "kafka_sasl_username": "cw-worker",
        "kafka_sasl_password": SASL_SECRET,
        **overrides,
    }
    return Settings(**values)  # type: ignore[arg-type]


def test_sasl_with_its_credentials_is_accepted() -> None:
    settings = sasl()
    assert settings.kafka_security_protocol == "SASL_SSL"
    assert settings.kafka_sasl_password is not None
    assert settings.kafka_sasl_password.get_secret_value() == SASL_SECRET


@pytest.mark.parametrize(
    ("missing", "variable"),
    [
        ({"kafka_sasl_mechanism": None}, "CW_KAFKA_SASL_MECHANISM"),
        ({"kafka_sasl_username": None}, "CW_KAFKA_SASL_USERNAME"),
        ({"kafka_sasl_password": None}, "CW_KAFKA_SASL_PASSWORD"),
    ],
)
def test_sasl_without_a_mechanism_user_or_password_is_refused(
    missing: dict[str, object], variable: str
) -> None:
    with pytest.raises(ValidationError, match=f"SASL_SSL needs {variable}"):
        sasl(**missing)


def test_sasl_from_the_environment_names_everything_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CW_KAFKA_SECURITY_PROTOCOL", "SASL_PLAINTEXT")
    with pytest.raises(ValidationError) as refused:
        Settings()
    message = str(refused.value)
    for variable in ("CW_KAFKA_SASL_MECHANISM", "CW_KAFKA_SASL_USERNAME", "CW_KAFKA_SASL_PASSWORD"):
        assert variable in message


def test_an_unknown_kafka_protocol_or_mechanism_is_refused() -> None:
    with pytest.raises(ValidationError, match="kafka_security_protocol"):
        Settings(kafka_security_protocol="TLS")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="kafka_sasl_mechanism"):
        sasl(kafka_sasl_mechanism="GSSAPI")


def test_a_temporal_api_key_turns_tls_on() -> None:
    settings = Settings(temporal_api_key=TEMPORAL_KEY)  # type: ignore[arg-type]
    assert settings.temporal_tls_enabled is True
    explicit = Settings(temporal_api_key=TEMPORAL_KEY, temporal_tls=False)  # type: ignore[arg-type]
    assert explicit.temporal_tls_enabled is False
    assert Settings(temporal_tls=True).temporal_tls_enabled is True


def test_a_client_certificate_with_its_key_turns_tls_on() -> None:
    settings = Settings(temporal_tls_cert=PEM_CERT, temporal_tls_key=PEM_KEY)  # type: ignore[arg-type]
    assert settings.temporal_tls_enabled is True


@pytest.mark.parametrize(
    "values",
    [{"temporal_tls_cert": PEM_CERT}, {"temporal_tls_key": PEM_KEY}],
)
def test_a_certificate_without_its_key_is_refused(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="go together"):
        Settings(**values)  # type: ignore[arg-type]


def test_an_api_key_and_a_client_certificate_together_are_refused() -> None:
    with pytest.raises(ValidationError, match="set one"):
        Settings(
            temporal_api_key=TEMPORAL_KEY,  # type: ignore[arg-type]
            temporal_tls_cert=PEM_CERT,  # type: ignore[arg-type]
            temporal_tls_key=PEM_KEY,  # type: ignore[arg-type]
        )


def test_a_client_certificate_with_tls_off_is_refused() -> None:
    with pytest.raises(ValidationError, match="unused"):
        Settings(
            temporal_tls=False,
            temporal_tls_cert=PEM_CERT,  # type: ignore[arg-type]
            temporal_tls_key=PEM_KEY,  # type: ignore[arg-type]
        )


def test_otel_headers_are_decoded_with_lower_case_names() -> None:
    settings = Settings(
        otel_protocol="http/protobuf",
        otel_headers="Authorization=Basic%20dXNlcjp0b2tlbg%3D%3D, X-Scope-OrgID = tenant-1 ,",  # type: ignore[arg-type]
    )
    assert settings.otel_header_map == {
        "authorization": "Basic dXNlcjp0b2tlbg==",
        "x-scope-orgid": "tenant-1",
    }
    assert parse_otel_headers("") == {}


@pytest.mark.parametrize(
    ("raw", "position"),
    [("Authorization Basic hidden", 1), ("=hidden", 1), ("a=b,Authorization hidden", 2)],
)
def test_unreadable_otel_headers_are_refused_without_echoing_them(raw: str, position: int) -> None:
    with pytest.raises(ValidationError, match=f"pair {position} is not key=value") as refused:
        Settings(otel_headers=raw)  # type: ignore[arg-type]
    assert "hidden" not in str(refused.value)


def test_an_unknown_otel_protocol_is_refused() -> None:
    with pytest.raises(ValidationError, match="otel_protocol"):
        Settings(otel_protocol="http/json")  # type: ignore[arg-type]


BASE_URL = "postgresql+psycopg://cw:p%40ss@db.internal:5432/compliancewatch"


def test_with_search_path_puts_the_schema_first_then_public() -> None:
    url = make_url(with_search_path(BASE_URL, "profile"))
    assert url.query == {"options": "-csearch_path=profile,public"}
    assert (url.username, url.password, url.host, url.port, url.database) == (
        "cw",
        "p@ss",
        "db.internal",
        5432,
        "compliancewatch",
    )


def test_with_search_path_replaces_an_existing_search_path_and_keeps_the_rest() -> None:
    before = (
        BASE_URL + "?sslmode=require&options=-c%20statement_timeout%3D5000%20-csearch_path%3Dold"
        "&application_name=cw"
    )
    url = make_url(with_search_path(before, "llm_gateway"))
    assert url.query == {
        "sslmode": "require",
        "application_name": "cw",
        "options": "-c statement_timeout=5000 -csearch_path=llm_gateway,public",
    }
    again = make_url(with_search_path(str(url.render_as_string(hide_password=False)), "qa"))
    assert again.query["options"] == "-c statement_timeout=5000 -csearch_path=qa,public"


@pytest.mark.parametrize(
    "options", ["-c%20search_path%3Dold", "--search_path%3Dold", "-csearch-path%3Dold"]
)
def test_with_search_path_recognises_every_spelling_of_the_option(options: str) -> None:
    url = make_url(with_search_path(f"{BASE_URL}?options={options}", "rulebook"))
    assert url.query == {"options": "-csearch_path=rulebook,public"}


@pytest.mark.parametrize("schema", ["Profile", "profile;drop", "", "a b", "public,evil"])
def test_with_search_path_refuses_anything_but_a_plain_schema_name(schema: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        with_search_path(BASE_URL, schema)
