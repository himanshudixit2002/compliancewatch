"""Business attributes that GST rule predicates and business profiles are written against.

The attributes live in ``data/attributes.yaml``. ``load()`` parses that file into the kernel's
``Ontology`` model and applies this package's house rules. The kernel owns the model, so code
that only evaluates predicates never imports this package or PyYAML.

The wording that puts each attribute to a person (a question, and a label per allowed value)
lives in ``data/wording.<language>.yaml``. ``load_wording()`` parses it into the kernel's
``OntologyWording`` and checks it against ``load()``.
"""

from collections.abc import Mapping
from importlib.resources import files
from importlib.resources.abc import Traversable

import yaml

from domain_kernel.ontology import Ontology, OntologyWording
from ontology._checks import OntologyCheckError, check

__all__ = [
    "VERSION",
    "WORDING_LANGUAGES",
    "WORDING_VERSION",
    "OntologyCheckError",
    "data_path",
    "load",
    "load_wording",
    "parse",
    "wording_path",
]

VERSION = "0.2.0"
"""Version of the attribute set this package ships; equals ``version`` in the YAML file."""

WORDING_VERSION = "0.1.0"
"""Version of the English wording; equals ``version`` in ``wording.en.yaml``. Wording is
versioned apart from the attribute set: rewording a question changes no predicate."""

WORDING_LANGUAGES = ("en",)
"""Languages this package ships wording for. Hindi arrives with the Hindi interface."""


def data_path() -> Traversable:
    """Location of the packaged attributes file."""
    return files("ontology") / "data" / "attributes.yaml"


def wording_path(language: str = "en") -> Traversable:
    """Location of the packaged wording for ``language``."""
    if language not in WORDING_LANGUAGES:
        raise OntologyCheckError(
            f"no wording for language {language!r}; this package ships {list(WORDING_LANGUAGES)}"
        )
    return files("ontology") / "data" / f"wording.{language}.yaml"


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


def load_wording(language: str = "en") -> OntologyWording:
    """Load the packaged wording for ``language`` and check it against ``load()``.

    A wording that does not fit the attribute set (a missing question or label, a label for a
    value that does not exist), or whose language or version disagrees with this package, is
    an OntologyCheckError; a malformed file is the kernel's OntologyDefinitionError.
    """
    data = yaml.safe_load(wording_path(language).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise OntologyCheckError(
            "the wording file must be a mapping with version, language, review_status and "
            "attributes"
        )
    wording = OntologyWording.from_mapping(data)
    problems = wording.check_against(load())
    if wording.language != language:
        problems.append(f"file language {wording.language} does not match {language}")
    if wording.version != WORDING_VERSION:
        problems.append(
            f"wording version {wording.version} does not match WORDING_VERSION {WORDING_VERSION}"
        )
    if problems:
        raise OntologyCheckError("; ".join(problems))
    return wording
