"""OpenTelemetry instruments of the obligation worker.

- ``obligation_guard_refusals_total{reason, source}``: what the guard kept from being made, by
  reason (``rule_withdrawn``, ``rule_superseded``, ``uncited``) and by what asked
  (``decision``: an applicability decision, ``window``: the rolling window). A withdrawn or
  uncited version counts once per decision or per business the window visits; a superseded one
  once per period it no longer governs. ``uncited`` above zero means a published version reached
  the service without a verified citation, which the rulebook's publication checks should have
  refused.

The name carries no unit and ends in ``_total``, as the collector's Prometheus exporter expects.
Without telemetry configured the global meter provider records nothing.
"""

from typing import Final

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Meter

GUARD_REFUSALS: Final = "obligation_guard_refusals_total"
DESCRIPTION: Final = "Obligations the guard did not make, by reason and by what asked"


def refusals_counter(meter: Meter) -> Counter:
    return meter.create_counter(GUARD_REFUSALS, description=DESCRIPTION)


REFUSALS: Final = refusals_counter(metrics.get_meter("obligation"))
"""The process's one instrument; tests make their own on a meter of their own."""


class GuardMetrics:
    def __init__(self, counter: Counter = REFUSALS) -> None:
        self._refusals = counter

    def refused(self, reason: str, source: str, count: int = 1) -> None:
        if count > 0:
            self._refusals.add(count, {"reason": reason, "source": source})
