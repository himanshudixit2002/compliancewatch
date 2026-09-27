"""House rules for the attribute file, on top of the structural checks the kernel makes."""

import re

from domain_kernel.ontology import AttributeType, Ontology

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
VALUE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")
STATE_CODE_PATTERN = re.compile(r"^[0-9]{2}$")
ENUM_TYPES = frozenset({AttributeType.ENUM, AttributeType.ORDERED_ENUM, AttributeType.ENUM_SET})


class OntologyCheckError(ValueError):
    """The attribute file breaks one of this package's rules."""


def check(ontology: Ontology) -> list[str]:
    """Return every rule the ontology breaks; an empty list means it passes."""
    problems: list[str] = []
    for attribute in ontology.attributes:
        key = attribute.key
        if not KEY_PATTERN.match(key):
            problems.append(f"{key}: key is not snake_case")
        if not attribute.definition.endswith("."):
            problems.append(f"{key}: definition must end with a period")
        if attribute.since is not None and _semver(attribute.since) > _semver(ontology.version):
            problems.append(
                f"{key}: since {attribute.since} is newer than version {ontology.version}"
            )
        if attribute.type in ENUM_TYPES:
            values = attribute.allowed_values or ()
            if len(values) < 2:
                problems.append(f"{key}: an enum needs at least two allowed values")
            pattern = STATE_CODE_PATTERN if key == "state_codes" else VALUE_PATTERN
            problems.extend(
                f"{key}: value {value!r} is malformed"
                for value in values
                if not pattern.match(value)
            )
    return problems


def _semver(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch
