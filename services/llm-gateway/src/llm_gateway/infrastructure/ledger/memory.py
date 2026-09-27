"""The cost ledger as a list in memory: tests, the fake container, and runs without Postgres."""

import threading
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from domain_kernel._validation import require_instance, require_int
from domain_kernel.ids import TenantId
from llm_gateway.domain.budgets import month_bounds
from llm_gateway.domain.features import Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.pricing import quantize_inr


class MemoryLedger:
    """Thread-safe; nothing survives the process."""

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._lock = threading.Lock()

    def add(self, entry: LedgerEntry) -> None:
        require_instance(entry, LedgerEntry, "entry")
        with self._lock:
            self._entries.append(entry)

    def spent_inr(
        self, *, tenant_id: TenantId | None, feature: Feature | None, month: date
    ) -> Decimal:
        start, end = month_bounds(month)
        with self._lock:
            entries = list(self._entries)
        total = sum(
            (
                entry.cost_inr
                for entry in entries
                if start <= entry.occurred_at < end
                and (tenant_id is None or entry.tenant_id == tenant_id)
                and (feature is None or entry.feature is feature)
            ),
            Decimal(0),
        )
        return quantize_inr(total)

    def recent(self, limit: int) -> Sequence[LedgerEntry]:
        """Newest first by ``occurred_at``; among equal instants the latest added comes first."""
        require_int(limit, "limit", minimum=0)
        with self._lock:
            newest_first = list(reversed(self._entries))
        newest_first.sort(key=lambda entry: entry.occurred_at, reverse=True)
        return tuple(newest_first[:limit])

    def entries(self) -> Sequence[LedgerEntry]:
        """Every entry in the order it was added."""
        with self._lock:
            return tuple(self._entries)

    def ping(self) -> bool:
        return True
