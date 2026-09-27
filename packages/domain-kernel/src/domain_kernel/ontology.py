"""The ontology model: attribute definitions, value coercion and predicate comparison.

The YAML file and its loader live in ``packages/ontology``; this module is what they build.
Profile values and predicate values are coerced to one canonical form per attribute type so
that equality and ordering mean the same thing everywhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Protocol

from domain_kernel.errors import (
    InvalidAttributeValueError,
    InvalidOperatorError,
    OntologyDefinitionError,
    UnknownAttributeError,
)
from domain_kernel.operators import (
    MULTI_VALUE_OPERATORS,
    ORDERED_OPERATORS,
    SET_OPERATORS,
    Operator,
)

if TYPE_CHECKING:
    from domain_kernel.predicates import Predicate

type Scalar = str | int | bool | Decimal | date
type AttributeValue = Scalar | frozenset[str]
"""Canonical profile value: a scalar, or a frozenset of members for enum_set attributes."""
type PredicateValue = Scalar | tuple[Scalar, ...]
"""Expected value of a predicate: a tuple for IN, NOT_IN and CONTAINS_ANY, a scalar otherwise."""

ATTRIBUTE_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
SEMVER_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class AttributeType(StrEnum):
    """Value type of an attribute; decides the canonical form and the allowed operators."""

    ENUM = "enum"
    ORDERED_ENUM = "ordered_enum"
    ENUM_SET = "enum_set"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    STRING = "string"


class AttributeSource(StrEnum):
    """Where a profile gets the value from."""

    GSTIN_LOOKUP = "gstin_lookup"
    USER_INPUT = "user_input"
    DERIVED = "derived"


ENUM_TYPES = frozenset({AttributeType.ENUM, AttributeType.ORDERED_ENUM, AttributeType.ENUM_SET})
NUMERIC_TYPES = frozenset({AttributeType.INTEGER, AttributeType.DECIMAL})

_EQUALITY_OPERATORS = frozenset({Operator.EQ, Operator.NEQ, Operator.IN, Operator.NOT_IN})
_COMPARABLE_OPERATORS = _EQUALITY_OPERATORS | ORDERED_OPERATORS

ALLOWED_OPERATORS: Mapping[AttributeType, frozenset[Operator]] = MappingProxyType(
    {
        AttributeType.ENUM: _EQUALITY_OPERATORS,
        AttributeType.ORDERED_ENUM: _COMPARABLE_OPERATORS,
        AttributeType.ENUM_SET: SET_OPERATORS,
        AttributeType.BOOLEAN: frozenset({Operator.EQ, Operator.NEQ}),
        AttributeType.INTEGER: _COMPARABLE_OPERATORS,
        AttributeType.DECIMAL: _COMPARABLE_OPERATORS,
        AttributeType.DATE: _COMPARABLE_OPERATORS,
        AttributeType.STRING: _EQUALITY_OPERATORS,
    }
)
"""Operators a predicate may use per attribute type."""

_ATTRIBUTE_KEYS = frozenset(
    {"key", "type", "definition", "source", "allowed_values", "min", "max", "since", "example"}
)
_REQUIRED_ATTRIBUTE_KEYS = frozenset({"key", "type", "definition", "source"})
_ONTOLOGY_KEYS = frozenset({"version", "attributes"})


@dataclass(frozen=True, slots=True)
class AttributeDefinition:
    """One attribute of the business profile and the values it accepts.

    ``allowed_values`` is the member list of the enum kinds; for ordered_enum its order is the
    rank. ``minimum`` and ``maximum`` bound integer and decimal attributes. ``example`` is
    stored in canonical form.
    """

    key: str
    type: AttributeType
    definition: str
    source: AttributeSource
    allowed_values: tuple[str, ...] = ()
    minimum: int | Decimal | None = None
    maximum: int | Decimal | None = None
    since: str | None = None
    example: object = None

    def __post_init__(self) -> None:
        key = _instance(self.key, str, "attribute key")
        if not ATTRIBUTE_KEY_PATTERN.fullmatch(key):
            raise OntologyDefinitionError(f"attribute key {key!r} must be lowercase snake_case")
        _instance(self.type, AttributeType, f"{key}: type")
        definition = _instance(self.definition, str, f"{key}: definition")
        if not definition.strip():
            raise OntologyDefinitionError(f"{key}: definition must not be blank")
        _instance(self.source, AttributeSource, f"{key}: source")
        self._check_allowed_values()
        _check_bound(self.minimum, self.type, key, "min")
        _check_bound(self.maximum, self.type, key, "max")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise OntologyDefinitionError(f"{key}: min {self.minimum} exceeds max {self.maximum}")
        if self.since is not None:
            since = _instance(self.since, str, f"{key}: since")
            if not SEMVER_PATTERN.fullmatch(since):
                raise OntologyDefinitionError(f"{key}: since must be semver, got {since!r}")
        if self.example is not None:
            try:
                canonical = self.coerce(self.example)
            except InvalidAttributeValueError as exc:
                raise OntologyDefinitionError(f"{key}: example is invalid: {exc.reason}") from exc
            object.__setattr__(self, "example", canonical)

    def _check_allowed_values(self) -> None:
        values = _instance(self.allowed_values, tuple, f"{self.key}: allowed_values")
        if self.type in ENUM_TYPES:
            if not values:
                raise OntologyDefinitionError(
                    f"{self.key}: {self.type.value} attributes need allowed_values"
                )
        elif values:
            raise OntologyDefinitionError(
                f"{self.key}: allowed_values are only for enum, ordered_enum and enum_set"
            )
        seen: set[str] = set()
        for value in values:
            text = _instance(value, str, f"{self.key}: allowed value")
            if not text.strip() or text != text.strip():
                raise OntologyDefinitionError(
                    f"{self.key}: allowed values must be non-blank without surrounding whitespace"
                )
            if text in seen:
                raise OntologyDefinitionError(f"{self.key}: duplicate allowed value {text!r}")
            seen.add(text)

    def coerce(self, raw: object) -> AttributeValue:
        """Canonical form of ``raw`` for this attribute.

        Raises InvalidAttributeValueError when the value does not fit the type, the allowed
        values or the bounds.
        """
        match self.type:
            case AttributeType.ENUM | AttributeType.ORDERED_ENUM:
                return self.member(raw)
            case AttributeType.ENUM_SET:
                return self.members(raw)
            case AttributeType.BOOLEAN:
                if isinstance(raw, bool):
                    return raw
                raise self._invalid(raw, "must be a bool")
            case AttributeType.INTEGER:
                if isinstance(raw, bool) or not isinstance(raw, int):
                    raise self._invalid(raw, "must be an int")
                return self._within_bounds(raw)
            case AttributeType.DECIMAL:
                return self._within_bounds(self._decimal(raw))
            case AttributeType.DATE:
                return self._date(raw)
            case AttributeType.STRING:  # pragma: no branch
                if isinstance(raw, str):
                    return raw
                raise self._invalid(raw, "must be a string")

    def member(self, raw: object) -> str:
        """``raw`` when it is one of the allowed values."""
        if isinstance(raw, str) and raw in self.allowed_values:
            return raw
        raise self._invalid(raw, f"is not one of {list(self.allowed_values)}")

    def members(self, raw: object) -> frozenset[str]:
        """``raw`` as a frozenset of allowed values; a list, tuple or set is accepted."""
        if isinstance(raw, str) or not isinstance(raw, list | tuple | set | frozenset):
            raise self._invalid(raw, "must be a list, tuple or set of allowed values")
        return frozenset(self.member(item) for item in raw)

    def rank(self, value: object) -> int | Decimal | date:
        """Position of ``value`` in the attribute's order: the member index for ordered_enum,
        the value itself for integer, decimal and date."""
        canonical = self.coerce(value)
        if self.type is AttributeType.ORDERED_ENUM:
            return self.allowed_values.index(canonical)
        if isinstance(canonical, bool) or not isinstance(canonical, int | Decimal | date):
            raise self._invalid(value, f"has no order on a {self.type.value} attribute")
        return canonical

    @classmethod
    def from_mapping(cls, data: object, *, index: int | None = None) -> AttributeDefinition:
        """Build a definition from one item of the ``attributes`` list.

        Mapping keys ``min`` and ``max`` feed ``minimum`` and ``maximum``; lists are copied.
        """
        where = "attributes" if index is None else f"attributes[{index}]"
        mapping = _mapping(data, where)
        _check_keys(
            mapping, allowed=_ATTRIBUTE_KEYS, required=_REQUIRED_ATTRIBUTE_KEYS, where=where
        )
        key = _text(mapping, "key", where)
        attribute_type = _enum(AttributeType, mapping["type"], "type", where)
        allowed_values: tuple[str, ...] = ()
        if "allowed_values" in mapping:
            raw_values = mapping["allowed_values"]
            if isinstance(raw_values, str) or not isinstance(raw_values, Sequence):
                raise OntologyDefinitionError(f"{where}: allowed_values must be a list")
            allowed_values = tuple(raw_values)
        try:
            return cls(
                key=key,
                type=attribute_type,
                definition=_text(mapping, "definition", where),
                source=_enum(AttributeSource, mapping["source"], "source", where),
                allowed_values=allowed_values,
                minimum=_check_bound(mapping.get("min"), attribute_type, key, "min"),
                maximum=_check_bound(mapping.get("max"), attribute_type, key, "max"),
                since=_optional_text(mapping, "since", where),
                example=mapping.get("example"),
            )
        except OntologyDefinitionError as exc:
            raise OntologyDefinitionError(f"{where}: {exc.detail}") from exc

    def _invalid(self, raw: object, why: str) -> InvalidAttributeValueError:
        return InvalidAttributeValueError(self.key, f"{raw!r} {why}")

    def _within_bounds(self, value: int | Decimal) -> int | Decimal:
        if self.minimum is not None and value < self.minimum:
            raise self._invalid(value, f"is below the minimum {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise self._invalid(value, f"is above the maximum {self.maximum}")
        return value

    def _decimal(self, raw: object) -> Decimal:
        if isinstance(raw, bool):
            raise self._invalid(raw, "must be a number")
        if isinstance(raw, Decimal):
            value = raw
        elif isinstance(raw, int):
            value = Decimal(raw)
        elif isinstance(raw, float):
            value = Decimal(str(raw))
        elif isinstance(raw, str):
            try:
                value = Decimal(raw)
            except InvalidOperation as exc:
                raise self._invalid(raw, "is not a decimal number") from exc
        else:
            raise self._invalid(raw, "must be a number")
        if not value.is_finite():
            raise self._invalid(raw, "must be finite")
        return value

    def _date(self, raw: object) -> date:
        if isinstance(raw, datetime):
            raise self._invalid(raw, "must be a date without a time")
        if isinstance(raw, date):
            return raw
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw)
            except ValueError as exc:
                raise self._invalid(raw, "is not an ISO date") from exc
        raise self._invalid(raw, "must be a date")


@dataclass(frozen=True, slots=True)
class Ontology:
    """A versioned set of attribute definitions, indexed by key."""

    version: str
    attributes: tuple[AttributeDefinition, ...]
    _by_key: Mapping[str, AttributeDefinition] = field(
        init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        version = _instance(self.version, str, "version")
        if not SEMVER_PATTERN.fullmatch(version):
            raise OntologyDefinitionError(f"version must be semver, got {version!r}")
        attributes = _instance(self.attributes, tuple, "attributes")
        by_key: dict[str, AttributeDefinition] = {}
        for index, item in enumerate(attributes):
            attribute = _instance(item, AttributeDefinition, f"attributes[{index}]")
            if attribute.key in by_key:
                raise OntologyDefinitionError(
                    f"attributes[{index}]: duplicate key {attribute.key!r}"
                )
            by_key[attribute.key] = attribute
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))

    def __contains__(self, key: object) -> bool:
        return key in self._by_key

    def __iter__(self) -> Iterator[AttributeDefinition]:
        return iter(self.attributes)

    def __len__(self) -> int:
        return len(self.attributes)

    def get(self, key: str) -> AttributeDefinition | None:
        return self._by_key.get(key)

    def require(self, key: str) -> AttributeDefinition:
        """The definition for ``key``, or UnknownAttributeError."""
        definition = self._by_key.get(key)
        if definition is None:
            raise UnknownAttributeError(key)
        return definition

    def validate_value(self, key: str, raw: object) -> AttributeValue:
        """Canonical form of one profile value."""
        return self.require(key).coerce(raw)

    def validate_attributes(self, attributes: Mapping[str, object]) -> dict[str, AttributeValue]:
        """Canonical form of a whole profile. Unknown keys and None values are errors."""
        result: dict[str, AttributeValue] = {}
        for key, raw in attributes.items():
            definition = self.require(key)
            if raw is None:
                raise InvalidAttributeValueError(key, "value must not be None")
            result[key] = definition.coerce(raw)
        return result

    def check_predicate(self, predicate: Predicate) -> None:
        """Raise unless the predicate names a known attribute and, when it carries an operator,
        the operator is allowed on that attribute type and the expected value coerces."""
        definition = self.require(predicate.attribute)
        operator, expected = predicate.operator, predicate.value
        if operator is None or expected is None:
            return
        _check_operator(definition, operator)
        if operator in SET_OPERATORS:
            items = (
                _many(expected, definition.key)
                if operator is Operator.CONTAINS_ANY
                else (_single(expected, definition.key),)
            )
            for item in items:
                definition.member(item)
        elif operator in MULTI_VALUE_OPERATORS:
            for item in _many(expected, definition.key):
                definition.coerce(item)
        else:
            definition.coerce(_single(expected, definition.key))

    def compare(
        self, key: str, operator: Operator, actual: object, expected: PredicateValue
    ) -> bool:
        """Apply ``operator`` between a profile value and a predicate value.

        Both sides are coerced first. A disallowed operator or a malformed value raises; the
        result is only ever a verdict on well-formed data.
        """
        definition = self.require(key)
        _check_operator(definition, operator)
        match operator:
            case Operator.EQ:
                return definition.coerce(actual) == definition.coerce(_single(expected, key))
            case Operator.NEQ:
                return definition.coerce(actual) != definition.coerce(_single(expected, key))
            case Operator.IN:
                choices = {definition.coerce(item) for item in _many(expected, key)}
                return definition.coerce(actual) in choices
            case Operator.NOT_IN:
                choices = {definition.coerce(item) for item in _many(expected, key)}
                return definition.coerce(actual) not in choices
            case Operator.GT | Operator.GTE | Operator.LT | Operator.LTE:
                rhs = definition.rank(_single(expected, key))
                return _ordered(operator, definition.rank(actual), rhs)
            case Operator.CONTAINS:
                return definition.member(_single(expected, key)) in definition.members(actual)
            case Operator.CONTAINS_ANY:  # pragma: no branch
                wanted = {definition.member(item) for item in _many(expected, key)}
                return not definition.members(actual).isdisjoint(wanted)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Ontology:
        """Build the ontology from the plain mapping a YAML file parses to.

        Top-level keys are ``version`` and ``attributes``; each attribute item takes ``key``,
        ``type``, ``definition``, ``source`` and optionally ``allowed_values``, ``min``, ``max``,
        ``since`` and ``example``. Every structural problem is an OntologyDefinitionError.
        """
        mapping = _mapping(data, "ontology")
        _check_keys(mapping, allowed=_ONTOLOGY_KEYS, required=_ONTOLOGY_KEYS, where="ontology")
        version = _text(mapping, "version", "ontology")
        items = mapping["attributes"]
        if isinstance(items, str) or not isinstance(items, Sequence):
            raise OntologyDefinitionError("ontology: attributes must be a list")
        attributes = tuple(
            AttributeDefinition.from_mapping(item, index=index) for index, item in enumerate(items)
        )
        return cls(version=version, attributes=attributes)


class _Comparable(Protocol):
    def __lt__(self, other: Any, /) -> bool: ...
    def __le__(self, other: Any, /) -> bool: ...
    def __gt__(self, other: Any, /) -> bool: ...
    def __ge__(self, other: Any, /) -> bool: ...


type _OrderedOperator = Literal[Operator.GT, Operator.GTE, Operator.LT, Operator.LTE]


def _ordered(operator: _OrderedOperator, lhs: _Comparable, rhs: _Comparable) -> bool:
    match operator:
        case Operator.GT:
            return lhs > rhs
        case Operator.GTE:
            return lhs >= rhs
        case Operator.LT:
            return lhs < rhs
        case Operator.LTE:  # pragma: no branch
            return lhs <= rhs


def _check_operator(definition: AttributeDefinition, operator: Operator) -> None:
    if operator not in ALLOWED_OPERATORS[definition.type]:
        raise InvalidOperatorError(definition.key, operator.value, definition.type.value)


def _single(expected: PredicateValue, key: str) -> Scalar:
    if isinstance(expected, tuple):
        raise InvalidAttributeValueError(key, "this operator takes one value, not a tuple")
    return expected


def _many(expected: PredicateValue, key: str) -> tuple[Scalar, ...]:
    if not isinstance(expected, tuple):
        raise InvalidAttributeValueError(key, "this operator takes a tuple of values")
    if not expected:
        raise InvalidAttributeValueError(key, "this operator needs at least one value")
    return expected


def _check_bound(raw: object, kind: AttributeType, key: str, name: str) -> int | Decimal | None:
    if raw is None:
        return None
    if kind not in NUMERIC_TYPES:
        raise OntologyDefinitionError(f"{key}: {name} is only allowed on integer and decimal")
    if isinstance(raw, bool) or not isinstance(raw, int | Decimal):
        raise OntologyDefinitionError(
            f"{key}: {name} must be an int or Decimal, got {raw.__class__.__name__}"
        )
    if kind is AttributeType.INTEGER and not isinstance(raw, int):
        raise OntologyDefinitionError(f"{key}: {name} on an integer attribute must be an int")
    if isinstance(raw, Decimal) and not raw.is_finite():
        raise OntologyDefinitionError(f"{key}: {name} must be finite")
    return raw


def _instance[T](value: object, kind: type[T], what: str) -> T:
    if not isinstance(value, kind):
        raise OntologyDefinitionError(
            f"{what} must be {kind.__name__}, got {value.__class__.__name__}"
        )
    return value


def _mapping(data: object, where: str) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise OntologyDefinitionError(f"{where} must be a mapping, got {data.__class__.__name__}")
    for key in data:
        if not isinstance(key, str):
            raise OntologyDefinitionError(f"{where}: keys must be strings, got {key!r}")
    return data


def _check_keys(
    mapping: Mapping[str, object], *, allowed: frozenset[str], required: frozenset[str], where: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise OntologyDefinitionError(f"{where}: unknown keys {sorted(unknown)}")
    missing = required - set(mapping)
    if missing:
        raise OntologyDefinitionError(f"{where}: missing keys {sorted(missing)}")


def _text(mapping: Mapping[str, object], key: str, where: str) -> str:
    raw = mapping.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise OntologyDefinitionError(f"{where}: {key} must be a non-empty string")
    return raw


def _optional_text(mapping: Mapping[str, object], key: str, where: str) -> str | None:
    raw = mapping.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise OntologyDefinitionError(f"{where}: {key} must be a string when given")
    return raw


def _enum[E: StrEnum](kind: type[E], raw: object, key: str, where: str) -> E:
    if not isinstance(raw, str):
        raise OntologyDefinitionError(f"{where}: {key} must be a string")
    try:
        return kind(raw)
    except ValueError as exc:
        raise OntologyDefinitionError(
            f"{where}: {key} {raw!r} is not one of {[m.value for m in kind]}"
        ) from exc
