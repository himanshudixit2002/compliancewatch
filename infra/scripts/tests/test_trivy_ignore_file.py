"""Every finding accepted in .trivyignore.yaml says why, and stops being accepted within 90 days.

Trivy reads the file in `make deps-scan`, the dependency-scan CI job, the nightly rescan and the
image scans. Trivy itself only honours ``expired_at``; these tests hold the rest of the policy
written at the top of the file.
"""

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
IGNORE_FILE = ROOT / ".trivyignore.yaml"
SECTIONS = {"vulnerabilities", "misconfigurations", "secrets", "licenses"}
LONGEST_ACCEPTANCE = dt.timedelta(days=90)
TODAY = dt.date(2026, 9, 29)


def problems(data: Any, today: dt.date) -> list[str]:
    if not isinstance(data, dict):
        return ["the file is not a mapping of Trivy sections"]
    found = [f"{name}: not a Trivy section" for name in sorted(set(data) - SECTIONS)]
    for name, section in sorted(data.items()):
        if not isinstance(section, list):
            found.append(f"{name}: not a list of entries")
            continue
        for entry in section:
            if not isinstance(entry, dict):
                found.append(f"{name}: {entry!r} is not an entry")
                continue
            label = f"{name}/{entry.get('id') or '<no id>'}"
            if not str(entry.get("id") or "").strip():
                found.append(f"{label}: no id")
            if not str(entry.get("statement") or "").strip():
                found.append(f"{label}: no statement")
            expired_at = entry.get("expired_at")
            if not isinstance(expired_at, dt.date):
                found.append(f"{label}: expired_at is not a date")
            elif expired_at - today > LONGEST_ACCEPTANCE:
                found.append(f"{label}: accepted until {expired_at}, more than 90 days out")
    return found


def test_the_repository_file_follows_the_policy() -> None:
    data = yaml.safe_load(IGNORE_FILE.read_text(encoding="utf-8"))
    assert problems(data, dt.date.today()) == []


def test_the_plain_ignore_format_is_not_used() -> None:
    # A .trivyignore line carries neither a statement nor an expiry date.
    assert not (ROOT / ".trivyignore").exists()


def test_a_complete_entry_passes() -> None:
    entry = {"id": "CVE-2026-0001", "statement": "dev tooling only", "expired_at": TODAY}
    assert problems({"vulnerabilities": [entry]}, TODAY) == []


def test_an_entry_without_a_statement_or_an_expiry_fails() -> None:
    assert problems({"vulnerabilities": [{"id": "CVE-2026-0001"}]}, TODAY) == [
        "vulnerabilities/CVE-2026-0001: no statement",
        "vulnerabilities/CVE-2026-0001: expired_at is not a date",
    ]


def test_an_entry_accepted_for_more_than_90_days_fails() -> None:
    entry = {
        "id": "DS-0002",
        "statement": "runs as root in the dev image",
        "expired_at": TODAY + dt.timedelta(days=91),
    }
    assert problems({"misconfigurations": [entry]}, TODAY) == [
        "misconfigurations/DS-0002: accepted until 2026-12-29, more than 90 days out"
    ]


def test_an_unknown_section_fails() -> None:
    assert problems({"vulnerabilites": []}, TODAY) == ["vulnerabilites: not a Trivy section"]
