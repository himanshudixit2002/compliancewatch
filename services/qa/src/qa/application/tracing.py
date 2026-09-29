"""A tracer that records nothing, for callers that do not trace."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from qa.domain.ports import AttributeValue


class NullSpan:
    def set_attribute(self, key: str, value: AttributeValue) -> None:
        return None


class NullTracer:
    @contextmanager
    def span(
        self, name: str, attributes: Mapping[str, AttributeValue] | None = None
    ) -> Iterator[NullSpan]:
        yield NullSpan()
