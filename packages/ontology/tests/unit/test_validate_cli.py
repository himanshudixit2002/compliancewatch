from pathlib import Path

import pytest

from ontology import VERSION
from ontology.validate import main

_CLEAN = (
    'version: "0.1.0"\n'
    "attributes:\n"
    "  - key: supply_type\n"
    "    type: enum\n"
    "    source: user_input\n"
    '    since: "0.1.0"\n'
    "    definition: Whether the business supplies goods, services or both.\n"
    "    allowed_values: [goods, services, both]\n"
    "    example: goods\n"
)


def test_packaged_file_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out, err = capsys.readouterr()
    assert VERSION in out
    assert "turnover_band" in out
    assert out.rstrip().endswith("attributes ok")
    assert err == ""


def test_file_flag_checks_a_draft_without_the_version_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = tmp_path / "draft.yaml"
    draft.write_text(_CLEAN.replace('version: "0.1.0"', 'version: "9.9.9"'), encoding="utf-8")
    assert main(["--file", str(draft)]) == 0
    out, _ = capsys.readouterr()
    assert "supply_type" in out
    assert "ontology 9.9.9:" in out


def test_house_rule_failure_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    draft = tmp_path / "draft.yaml"
    draft.write_text(_CLEAN.replace("or both.", "or both"), encoding="utf-8")
    assert main(["--file", str(draft)]) == 1
    _, err = capsys.readouterr()
    assert "invalid" in err
    assert "period" in err


def test_corrupted_mapping_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text('version: "0.1.0"\nattributes:\n  - key: supply_type\n', encoding="utf-8")
    assert main(["--file", str(broken)]) == 1
    _, err = capsys.readouterr()
    assert "invalid" in err
    assert "missing keys" in err


def test_non_mapping_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    listing = tmp_path / "list.yaml"
    listing.write_text("- version\n- attributes\n", encoding="utf-8")
    assert main(["--file", str(listing)]) == 1
    _, err = capsys.readouterr()
    assert "mapping" in err


def test_unparseable_yaml_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: [\n", encoding="utf-8")
    assert main(["--file", str(bad)]) == 1
    _, err = capsys.readouterr()
    assert "invalid" in err


def test_missing_file_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--file", str(tmp_path / "missing.yaml")]) == 1
    _, err = capsys.readouterr()
    assert "invalid" in err


def test_badly_encoded_file_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "latin1.yaml"
    bad.write_bytes(b'version: "0.1.0"\nattributes: []\n# caf\xe9\n')
    assert main(["--file", str(bad)]) == 1
    assert "invalid" in capsys.readouterr().err


def test_packaged_version_mismatch_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("ontology.validate.VERSION", "9.9.9")
    assert main([]) == 1
    assert "does not match" in capsys.readouterr().err
