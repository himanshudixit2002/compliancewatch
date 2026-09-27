"""Check the attribute file from the command line.

Run as ``ontology-validate`` or ``python -m ontology.validate``. Exit code 0 prints one line
per attribute and the version; exit code 1 prints what is wrong to stderr.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from domain_kernel.errors import OntologyDefinitionError
from domain_kernel.ontology import Ontology
from ontology import VERSION, data_path, parse
from ontology._checks import OntologyCheckError, check


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontology-validate", description=__doc__)
    parser.add_argument(
        "--file", type=Path, default=None, help="validate this file instead of the packaged one"
    )
    args = parser.parse_args(argv)
    path: Path | None = args.file
    try:
        text = (path or data_path()).read_text(encoding="utf-8")
        ontology = Ontology.from_mapping(parse(text))
        problems = check(ontology)
        if path is None and ontology.version != VERSION:
            problems.append(f"file version {ontology.version} does not match VERSION {VERSION}")
        if problems:
            raise OntologyCheckError("\n".join(problems))
    except (
        OSError,
        UnicodeDecodeError,
        yaml.YAMLError,
        OntologyDefinitionError,
        OntologyCheckError,
    ) as exc:
        sys.stderr.write(f"ontology: invalid: {exc}\n")
        return 1
    for attribute in ontology.attributes:
        sys.stdout.write(f"{attribute.key:<28} {attribute.type.value}\n")
    sys.stdout.write(f"ontology {ontology.version}: {len(ontology.attributes)} attributes ok\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
