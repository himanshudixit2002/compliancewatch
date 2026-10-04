"""How every Kafka client of a process reaches the brokers.

``KafkaClientConfig`` holds the bootstrap servers and the security settings (``CW_KAFKA_*``):
the dev stack's Redpanda takes plain connections, a managed cluster SASL/SCRAM over TLS.
``aiokafka_kwargs()`` are the arguments ``AIOKafkaProducer``, ``AIOKafkaConsumer`` and
``AIOKafkaAdminClient`` all take, so the outbox relay, the consumers and the topic tooling
connect the same way. A bare bootstrap string is a plain connection
(``KafkaClientConfig.of("localhost:19092")``).
"""

import ssl
from dataclasses import dataclass, field
from typing import Any, Self

from aiokafka.helpers import create_ssl_context
from pydantic import SecretStr

from py_common.settings import KafkaSaslMechanism, KafkaSecurityProtocol, Settings

TLS_PROTOCOLS: frozenset[str] = frozenset({"SSL", "SASL_SSL"})
SASL_PROTOCOLS: frozenset[str] = frozenset({"SASL_PLAINTEXT", "SASL_SSL"})


@dataclass(frozen=True, slots=True)
class KafkaClientConfig:
    bootstrap_servers: str
    security_protocol: KafkaSecurityProtocol = "PLAINTEXT"
    sasl_mechanism: KafkaSaslMechanism | None = None
    sasl_username: str | None = None
    sasl_password: SecretStr | None = field(default=None, repr=False)
    ssl_cafile: str | None = None
    """The certificate authorities that sign the brokers' certificates; the system's when
    empty."""

    def __post_init__(self) -> None:
        if not self.bootstrap_servers.strip():
            raise ValueError("bootstrap_servers must not be blank")
        if self.uses_sasl and (
            self.sasl_mechanism is None
            or not self.sasl_username
            or self.sasl_password is None
            or not self.sasl_password.get_secret_value()
        ):
            raise ValueError(
                f"security_protocol {self.security_protocol} needs a SASL mechanism, username "
                "and password"
            )

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            bootstrap_servers=settings.kafka_bootstrap,
            security_protocol=settings.kafka_security_protocol,
            sasl_mechanism=settings.kafka_sasl_mechanism,
            sasl_username=settings.kafka_sasl_username,
            sasl_password=settings.kafka_sasl_password,
            ssl_cafile=settings.kafka_ssl_cafile or None,
        )

    @classmethod
    def of(cls, target: "KafkaClientConfig | str") -> "KafkaClientConfig":
        """``target`` itself, or a plain connection to the bootstrap servers it names."""
        return target if isinstance(target, KafkaClientConfig) else cls(bootstrap_servers=target)

    @property
    def uses_tls(self) -> bool:
        return self.security_protocol in TLS_PROTOCOLS

    @property
    def uses_sasl(self) -> bool:
        return self.security_protocol in SASL_PROTOCOLS

    def ssl_context(self) -> ssl.SSLContext | None:
        """The TLS context for ``SSL`` and ``SASL_SSL``; None for a plain connection."""
        if not self.uses_tls:
            return None
        context: ssl.SSLContext = create_ssl_context(cafile=self.ssl_cafile)
        return context

    def aiokafka_kwargs(self) -> dict[str, Any]:
        """``bootstrap_servers``, ``security_protocol`` and, when the protocol uses them, the
        SASL credentials (``sasl_mechanism``, ``sasl_plain_username``, ``sasl_plain_password``)
        and ``ssl_context``."""
        kwargs: dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "security_protocol": self.security_protocol,
        }
        if self.uses_sasl and self.sasl_password is not None:
            kwargs.update(
                sasl_mechanism=self.sasl_mechanism,
                sasl_plain_username=self.sasl_username,
                sasl_plain_password=self.sasl_password.get_secret_value(),
            )
        context = self.ssl_context()
        if context is not None:
            kwargs["ssl_context"] = context
        return kwargs


__all__ = ["KafkaClientConfig"]
