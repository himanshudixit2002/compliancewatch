"""The producer the relay and the consumer's dead-letter path publish through."""

from collections.abc import Sequence
from typing import Protocol, Self

from aiokafka import AIOKafkaProducer

from py_common.kafka import KafkaClientConfig


class MessageProducer(Protocol):
    async def send(
        self, topic: str, *, key: bytes, value: bytes, headers: Sequence[tuple[str, bytes]]
    ) -> None: ...


class AiokafkaProducer:
    """Idempotent, acks-all producer. Construct and start inside a running event loop.

    ``kafka`` is the cluster and its credentials (``KafkaClientConfig.from_settings``), or bare
    bootstrap servers for a plain connection."""

    def __init__(
        self,
        kafka: KafkaClientConfig | str,
        *,
        client_id: str = "cw-outbox",
        request_timeout_ms: int = 10_000,
    ) -> None:
        self._kafka = KafkaClientConfig.of(kafka)
        self._client_id = client_id
        self._request_timeout_ms = request_timeout_ms
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        if self._producer is None:
            self._producer = AIOKafkaProducer(
                **self._kafka.aiokafka_kwargs(),
                client_id=self._client_id,
                enable_idempotence=True,
                acks="all",
                request_timeout_ms=self._request_timeout_ms,
            )
            await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def send(
        self, topic: str, *, key: bytes, value: bytes, headers: Sequence[tuple[str, bytes]]
    ) -> None:
        if self._producer is None:
            raise RuntimeError("producer is not started")
        await self._producer.send_and_wait(topic, value, key=key, headers=list(headers))
