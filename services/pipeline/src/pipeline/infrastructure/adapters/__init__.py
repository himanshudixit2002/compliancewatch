"""Source adapters: one module per regulator site, the registry to pick them by key."""

from pipeline.infrastructure.adapters.registry import (
    SOURCES,
    SourceSpec,
    build_adapter,
    source_id_for,
)

__all__ = ["SOURCES", "SourceSpec", "build_adapter", "source_id_for"]
