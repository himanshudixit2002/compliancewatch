"""Source adapters: one module per regulator site, the registry of adapter types and built-in
sources to pick them by key, and the catalog that serves them by id."""

from pipeline.infrastructure.adapters.registry import (
    ADAPTER_TYPES,
    SOURCES,
    AdapterType,
    RegistryCatalog,
    SourceSpec,
    build_adapter,
    source_id_for,
)

__all__ = [
    "ADAPTER_TYPES",
    "SOURCES",
    "AdapterType",
    "RegistryCatalog",
    "SourceSpec",
    "build_adapter",
    "source_id_for",
]
