"""The Kafka client arguments, from settings and from a bare bootstrap string."""

import ssl

import pytest
from pydantic import SecretStr

from py_common import kafka as kafka_module
from py_common.kafka import KafkaClientConfig
from py_common.settings import Settings

BROKERS = "broker-1.example:9092,broker-2.example:9092"
SCRAM_USER = "cw-relay"
SCRAM_SECRET = "scram-test-value"  # a test value, not a credential


def managed(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "kafka_bootstrap": BROKERS,
        "kafka_security_protocol": "SASL_SSL",
        "kafka_sasl_mechanism": "SCRAM-SHA-512",
        "kafka_sasl_username": SCRAM_USER,
        "kafka_sasl_password": SCRAM_SECRET,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_sasl_ssl_with_scram_gives_the_credentials_and_a_tls_context() -> None:
    kwargs = KafkaClientConfig.from_settings(managed()).aiokafka_kwargs()
    context = kwargs.pop("ssl_context")
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert kwargs == {
        "bootstrap_servers": BROKERS,
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "SCRAM-SHA-512",
        "sasl_plain_username": SCRAM_USER,
        "sasl_plain_password": SCRAM_SECRET,
    }


def test_sasl_over_plaintext_sends_the_credentials_without_tls() -> None:
    config = KafkaClientConfig.from_settings(managed(kafka_security_protocol="SASL_PLAINTEXT"))
    kwargs = config.aiokafka_kwargs()
    assert "ssl_context" not in kwargs
    assert kwargs["sasl_mechanism"] == "SCRAM-SHA-512"
    assert (config.uses_sasl, config.uses_tls) == (True, False)


def test_ssl_alone_has_a_tls_context_and_no_credentials() -> None:
    config = KafkaClientConfig(BROKERS, security_protocol="SSL")
    kwargs = config.aiokafka_kwargs()
    assert isinstance(kwargs.pop("ssl_context"), ssl.SSLContext)
    assert kwargs == {"bootstrap_servers": BROKERS, "security_protocol": "SSL"}


def test_the_ca_file_verifies_the_brokers(monkeypatch: pytest.MonkeyPatch) -> None:
    cafiles: list[str | None] = []

    def create_ssl_context(*, cafile: str | None = None) -> ssl.SSLContext:
        cafiles.append(cafile)
        return ssl.create_default_context()

    monkeypatch.setattr(kafka_module, "create_ssl_context", create_ssl_context)
    settings = managed(kafka_ssl_cafile="/etc/kafka/ca.pem")
    assert "ssl_context" in KafkaClientConfig.from_settings(settings).aiokafka_kwargs()
    assert KafkaClientConfig.from_settings(managed()).ssl_context() is not None
    assert cafiles == ["/etc/kafka/ca.pem", None]


def test_a_bare_bootstrap_string_is_a_plain_connection() -> None:
    config = KafkaClientConfig.of("localhost:19092")
    assert config.aiokafka_kwargs() == {
        "bootstrap_servers": "localhost:19092",
        "security_protocol": "PLAINTEXT",
    }
    assert config.ssl_context() is None
    assert KafkaClientConfig.of(config) is config


def test_the_default_settings_are_the_dev_stack() -> None:
    kwargs = KafkaClientConfig.from_settings(Settings(_env_file=None)).aiokafka_kwargs()
    assert kwargs == {"bootstrap_servers": "localhost:19092", "security_protocol": "PLAINTEXT"}


def test_the_password_stays_out_of_the_repr() -> None:
    config = KafkaClientConfig.from_settings(managed())
    assert SCRAM_SECRET not in repr(config)


@pytest.mark.parametrize(
    "missing",
    [
        {"sasl_mechanism": None},
        {"sasl_username": ""},
        {"sasl_password": None},
        {"sasl_password": SecretStr("")},
    ],
)
def test_sasl_without_its_credentials_is_refused(missing: dict[str, object]) -> None:
    values: dict[str, object] = {
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "SCRAM-SHA-256",
        "sasl_username": SCRAM_USER,
        "sasl_password": SecretStr(SCRAM_SECRET),
        **missing,
    }
    with pytest.raises(ValueError, match="SASL mechanism, username and password"):
        KafkaClientConfig(BROKERS, **values)  # type: ignore[arg-type]


def test_blank_bootstrap_servers_are_refused() -> None:
    with pytest.raises(ValueError, match="bootstrap_servers"):
        KafkaClientConfig.of(" ")
