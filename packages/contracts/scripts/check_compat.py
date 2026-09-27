"""Backward compatibility of the event schemas against a base revision (the pull request's base).

A change is backward compatible when every message the base schemas accepted is still accepted:
consumers built against the base keep working. The check therefore validates the base revision's
golden examples against the head schemas. It also refuses a removed schema file (a breaking
change needs a new ``v<major>`` file next to the old one), a schema whose content changed without
an ``x-version`` bump, and a version that went down.

Usage, from the repo root::

    uv run python packages/contracts/scripts/check_compat.py --base-ref origin/main
    uv run python packages/contracts/scripts/check_compat.py --base-dir <dir> --head-dir <dir>

Exit status 1 with one line per finding when the change is not compatible.
"""

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

REPO = Path(__file__).resolve().parents[3]
EVENTS_DIR = Path("packages/contracts/events")
FORMAT_CHECKER = Draft202012Validator.FORMAT_CHECKER


def load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"{path}: not a JSON object")
    return document


def version_tuple(text: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def without_version(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "x-version"}


def topic_of(schema_file: Path) -> str:
    return schema_file.name.removesuffix(".json").rpartition(".v")[0]


def extract_base(ref: str) -> Path:
    """The base revision's events directory, extracted with ``git archive`` into a temp dir."""
    target = Path(tempfile.mkdtemp(prefix="cw-events-base-"))
    result = subprocess.run(
        ["git", "archive", "--format=tar", ref, str(EVENTS_DIR)],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        if "did not match any files" in message or "not a valid object name" in message:
            return target
        raise SystemExit(f"git archive {ref} failed: {message}")
    with tarfile.open(fileobj=BytesIO(result.stdout)) as archive:
        archive.extractall(target, filter="data")
    return target / EVENTS_DIR


def check(base: Path, head: Path) -> list[str]:
    findings: list[str] = []
    base_schemas = sorted((base / "schemas").glob("*.json")) if (base / "schemas").exists() else []
    if not base_schemas:
        return findings
    head_validators: dict[str, Draft202012Validator] = {}
    for base_file in base_schemas:
        head_file = head / "schemas" / base_file.name
        if not head_file.exists():
            findings.append(
                f"{base_file.name}: removed; a breaking change is a new v<major> file, and the"
                " old one stays until every consumer has moved"
            )
            continue
        base_doc, head_doc = load(base_file), load(head_file)
        base_version, head_version = base_doc["x-version"], head_doc["x-version"]
        if version_tuple(head_version) < version_tuple(base_version):
            findings.append(
                f"{base_file.name}: x-version went down, {base_version} -> {head_version}"
            )
        elif head_version == base_version and without_version(head_doc) != without_version(
            base_doc
        ):
            findings.append(
                f"{base_file.name}: content changed but x-version is still {base_version}"
            )
        head_validators[topic_of(head_file)] = Draft202012Validator(
            head_doc, format_checker=FORMAT_CHECKER
        )
    envelope = head_validators.get("envelope")
    examples_dir = base / "examples"
    for example in sorted(examples_dir.rglob("*.json")) if examples_dir.exists() else []:
        message = load(example)
        label = f"examples/{example.parent.name}/{example.name}"
        if envelope is not None:
            try:
                envelope.validate(message)
            except ValidationError as exc:
                findings.append(f"{label}: base envelope example rejected by head: {exc.message}")
                continue
        if example.parent.name == "envelope":
            continue
        validator = head_validators.get(message["topic"])
        if validator is None:
            continue
        try:
            validator.validate(message["payload"])
        except ValidationError as exc:
            findings.append(f"{label}: base example rejected by head schema: {exc.message}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-ref", default="origin/main", help="git ref of the base revision")
    parser.add_argument(
        "--base-dir", type=Path, help="events directory of the base (instead of --base-ref)"
    )
    parser.add_argument("--head-dir", type=Path, default=REPO / EVENTS_DIR)
    args = parser.parse_args(argv)
    base = args.base_dir if args.base_dir is not None else extract_base(args.base_ref)
    findings = check(base, args.head_dir)
    for finding in findings:
        sys.stderr.write(f"incompatible: {finding}\n")
    if findings:
        return 1
    sys.stdout.write(
        f"event schemas are backward compatible with {args.base_dir or args.base_ref}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
