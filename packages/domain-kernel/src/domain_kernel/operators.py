"""Comparison operators a predicate can use."""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class Operator(StrEnum):
    """How a predicate compares a profile value with its expected value.

    Booleans use EQ and NEQ with True and False. IN, NOT_IN and CONTAINS_ANY take a tuple of
    values; the others take one.
    """

    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    CONTAINS_ANY = "contains_any"

    @property
    def symbol(self) -> str:
        """Short form used when describing a predicate, such as ``>=`` or ``contains any``."""
        return _SYMBOLS[self]


_SYMBOLS: Mapping[Operator, str] = MappingProxyType(
    {
        Operator.EQ: "=",
        Operator.NEQ: "!=",
        Operator.IN: "in",
        Operator.NOT_IN: "not in",
        Operator.GT: ">",
        Operator.GTE: ">=",
        Operator.LT: "<",
        Operator.LTE: "<=",
        Operator.CONTAINS: "contains",
        Operator.CONTAINS_ANY: "contains any",
    }
)

ORDERED_OPERATORS = frozenset({Operator.GT, Operator.GTE, Operator.LT, Operator.LTE})
"""Operators that compare by rank; the attribute type must have an order."""

MULTI_VALUE_OPERATORS = frozenset({Operator.IN, Operator.NOT_IN, Operator.CONTAINS_ANY})
"""Operators whose expected value is a tuple."""

SET_OPERATORS = frozenset({Operator.CONTAINS, Operator.CONTAINS_ANY})
"""Operators that apply to enum_set attributes."""
