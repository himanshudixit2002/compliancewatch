import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.confidence import CERTAIN, REVIEW_THRESHOLD, ZERO, Confidence
from domain_kernel.errors import InvariantViolationError


@pytest.mark.parametrize("value", [0, 0.0, 1, 1.0, 0.8])
def test_values_inside_the_unit_interval_are_accepted(value: float) -> None:
    assert Confidence(value).value == value


@pytest.mark.parametrize("value", [-0.01, 1.01, math.nan, math.inf, -math.inf, True, "0.5"])
def test_values_outside_or_of_the_wrong_type_are_rejected(value: object) -> None:
    with pytest.raises(InvariantViolationError, match="confidence"):
        Confidence(value)  # type: ignore[arg-type]


def test_review_threshold_defaults_to_the_module_constant() -> None:
    assert REVIEW_THRESHOLD == 0.8
    assert Confidence(0.79).needs_review()
    assert not Confidence(0.8).needs_review()
    assert Confidence(0.9).needs_review(threshold=0.95)
    assert not Confidence(0.9).needs_review(threshold=0.5)


def test_singletons_and_ordering() -> None:
    assert Confidence(0.0) == ZERO
    assert Confidence(1.0) == CERTAIN
    assert ZERO < Confidence(0.5) < CERTAIN
    assert sorted([CERTAIN, ZERO, Confidence(0.3)]) == [ZERO, Confidence(0.3), CERTAIN]
    assert not CERTAIN.needs_review()
    assert ZERO.needs_review()


@given(value=st.floats(0, 1), threshold=st.floats(0, 1))
def test_needs_review_iff_below_threshold(value: float, threshold: float) -> None:
    assert Confidence(value).needs_review(threshold) == (value < threshold)
