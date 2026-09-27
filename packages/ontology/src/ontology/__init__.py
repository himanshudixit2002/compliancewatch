"""Business attributes that GST rule predicates and business profiles are written against.

The attributes live in ``data/attributes.yaml``. ``load()`` parses that file into the kernel's
``Ontology`` model and applies this package's house rules. The kernel owns the model, so code
that only evaluates predicates never imports this package or PyYAML.
"""

from collections.abc import Mapping
from importlib.resources import files
from importlib.resources.abc import Traversable

import yaml

from domain_kernel.ontology import Ontology
from ontology._checks import OntologyCheckError, check

__all__ = ["VERSION", "OntologyCheckError", "data_path", "load", "parse"]

VERSION = "0.2.0"
"""Version of the attribute set this package ships; equals ``version`` in the YAML file."""


def data_path() -> Traversable:
    """Location of the packaged attributes file."""
    return files("ontology") / "data" / "attributes.yaml"


def parse(text: str) -> Mapping[str, object]:
    """Parse YAML text into the plain mapping that ``Ontology.from_mapping`` expects."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise OntologyCheckError("the ontology file must be a mapping with version and attributes")
    return data


def load() -> Ontology:
    """Load, validate and return the packaged ontology."""
    ontology = Ontology.from_mapping(parse(data_path().read_text(encoding="utf-8")))
    problems = check(ontology)
    if ontology.version != VERSION:
        problems.append(f"file version {ontology.version} does not match VERSION {VERSION}")
    if problems:
        raise OntologyCheckError("; ".join(problems))
    return ontology
