"""Lookup providers: the manual one (no account) and a static one for demos and tests."""

from collections.abc import Mapping
from datetime import date

from domain_kernel.identifiers import Gstin
from profile_service.domain.lookup import GstinLookupResult


class ManualLookupProvider:
    """No provider is configured: every lookup is unavailable and the person fills the profile."""

    def lookup(self, gstin: Gstin) -> GstinLookupResult | None:
        return None


class StaticLookupProvider:
    """Answers from a fixed table; what the demo tenant and the tests use."""

    def __init__(self, results: Mapping[str, GstinLookupResult]) -> None:
        self._results = dict(results)
        self.calls: list[Gstin] = []

    def lookup(self, gstin: Gstin) -> GstinLookupResult | None:
        self.calls.append(gstin)
        return self._results.get(gstin.value)


DEMO_LOOKUPS: Mapping[str, GstinLookupResult] = {
    "29ABCDE1234F1Z5": GstinLookupResult(
        Gstin("29ABCDE1234F1Z5"),
        legal_name="Acme Traders Private Limited",
        trade_name="Acme Bengaluru",
        registration_type="regular",
        gstin_status="active",
        state_code="29",
        constitution="private_limited",
        registered_since=date(2019, 7, 1),
    ),
}
"""Made-up demo entries for the static provider; never a real registration."""
