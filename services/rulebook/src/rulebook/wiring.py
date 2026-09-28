"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from rulebook.application.documents import ReadDocument, RegisterDocument
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.settings import RulebookSettings


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: RulebookSettings
    unit_of_work: KnowledgeUnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    register_document: RegisterDocument
    read_document: ReadDocument
