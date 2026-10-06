"""Source adapters: one module per regulator site, the registry of adapter types and built-in
sources to pick them by key, and the catalogs that serve them by id: the built-in sources
(``RegistryCatalog``) and the sources the store holds (``StoreCatalog``)."""

from pipeline.infrastructure.adapters.catalog import RegistryAdapterTypes, StoreCatalog
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
    "RegistryAdapterTypes",
    "RegistryCatalog",
    "SourceSpec",
    "StoreCatalog",
    "build_adapter",
    "source_id_for",
]
