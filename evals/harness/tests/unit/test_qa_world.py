"""The KAG world: read from world.yaml, then built through each service's API."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from cw_evals.providers import gateway_client
from cw_evals.qa.world import Services, WorldError, build_world, load_world

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "golden"
EXTENSIONS = {"gstr3b_extension_2025_09", "gstr3b_extension_2026_03"}
NOTIFICATIONS = {"amendment_02_2017_2025_03", "rescission_27_2022_2024_07"}
SEED_RULES = {
    "gstr3b_monthly",
    "gstr3b_quarterly_group_a",
    "gstr3b_quarterly_group_b",
    "gstr9_annual",
}


def test_the_world_file_reads_with_its_keys() -> None:
    spec = load_world(GOLDEN)
    assert [d.key for d in spec.documents] == [
        "n01_2026",
        "n17_2025",
        "n15_2025",
        "n10_2025",
        "n13_2024",
    ]
    assert (spec.label_status, spec.reviewed_by) == ("draft", "")
    assert len(spec.entities) == 20
    assert {r.rule_key for r in spec.rules} == SEED_RULES | EXTENSIONS | NOTIFICATIONS
    assert [b.key for b in spec.businesses] == ["acme_monthly", "qrmp_delhi"]
    assert spec.document("n01_2026").published_on == date(2026, 4, 21)
    assert spec.clause_text("n17_2025", "en.p5") is not None
    assert spec.clause_text("n17_2025", "en.p99") is None
    assert spec.clause_text("n99_2099", "en.p1") is None
    assert spec.effective_from("gstr3b_monthly") == date(2026, 4, 1)
    assert spec.effective_from("gstr3b_extension_2026_03") == date(2026, 4, 20)


def test_rules_in_force_follow_their_start_dates() -> None:
    spec = load_world(GOLDEN)
    assert spec.rules_in_force(date(2025, 10, 20)) == {"gstr3b_extension_2025_09"} | NOTIFICATIONS
    assert spec.rules_in_force(date(2026, 4, 10)) == SEED_RULES | NOTIFICATIONS | {
        "gstr3b_extension_2025_09"
    }
    assert spec.rules_in_force(date(2026, 4, 22)) == SEED_RULES | NOTIFICATIONS | EXTENSIONS


def test_unknown_keys_are_world_errors() -> None:
    spec = load_world(GOLDEN)
    for lookup in (
        lambda: spec.document("n99_2099"),
        lambda: spec.rule("gstr99"),
        lambda: spec.business("acme_weekly"),
    ):
        with pytest.raises(WorldError, match="no "):
            lookup()


@pytest.mark.parametrize(
    ("text", "message"),
    [("- a list\n", "must be a mapping"), ("world_id: x\n", "seed_calendar")],
)
def test_a_malformed_world_file_is_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "qa" / "kag" / "world.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(WorldError, match=message):
        load_world(tmp_path)


@pytest.fixture(scope="module")
def world() -> Iterator[Services]:
    with gateway_client() as gateway, build_world(load_world(GOLDEN), gateway) as services:
        yield services


def test_every_version_is_published_in_force_from_its_start(world: Services) -> None:
    found = world.rulebook.get("/v1/rulebook/rule-versions", params={"as_of": "2026-09-28"})
    assert {(v["rule_key"], v["status"]) for v in found.json()} == {
        (key, "published") for key in SEED_RULES | EXTENSIONS | NOTIFICATIONS
    }


def test_the_relations_are_approved_from_their_versions(world: Services) -> None:
    found = []
    for key in (
        "gstr3b_extension_2026_03",
        "gstr3b_extension_2025_09",
        "amendment_02_2017_2025_03",
    ):
        params = {"from_rule_version_id": str(world.versions[key].value)}
        found += world.rulebook.get("/v1/rulebook/relations", params=params).json()
    assert sorted((r["relation"], r["period_label"], r["new_due_on"]) for r in found) == [
        ("amends", None, None),
        ("extends_deadline", "2025-09", "2025-10-25"),
        ("extends_deadline", "2025-26 Q2", "2025-10-25"),
        ("extends_deadline", "2026-03", "2026-04-21"),
    ]
    assert world.open_groups == (("section", "3"),)


def test_the_businesses_get_the_obligations_of_the_rules_that_apply(world: Services) -> None:
    titles = {}
    for key, node in world.businesses.items():
        headers = {"x-tenant-id": str(world.tenants[key].value)}
        found = world.obligation.get(
            "/v1/obligation/obligations", params={"business_id": str(node.value)}, headers=headers
        ).json()
        titles[key] = [(o["title"], o["due_at"][:10]) for o in found]
    assert len(titles["acme_monthly"]) == 13
    assert titles["acme_monthly"][0] == ("File GSTR-3B for the month (2026-04)", "2026-05-20")
    assert titles["acme_monthly"][-1] == (
        "File GSTR-9 for the financial year (2026-27)",
        "2027-12-31",
    )
    assert titles["qrmp_delhi"] == [
        ("File GSTR-3B for the quarter (QRMP) (2026-27 Q1)", "2026-07-24"),
        ("File GSTR-3B for the quarter (QRMP) (2026-27 Q2)", "2026-10-24"),
        ("File GSTR-3B for the quarter (QRMP) (2026-27 Q3)", "2027-01-24"),
        ("File GSTR-3B for the quarter (QRMP) (2026-27 Q4)", "2027-04-24"),
    ]
    assert world.tenant_for(None) == world.tenants["acme_monthly"]


def test_every_clause_is_embedded_for_search(world: Services) -> None:
    answer = world.rulebook.get(
        "/v1/rulebook/clauses/unembedded", params={"model": "fake/hash-ngram-512"}
    )
    assert answer.json() == []
    hits = world.rulebook.post(
        "/v1/rulebook/search", json={"text": "serial number 49", "as_of": "2026-09-28", "k": 3}
    ).json()
    assert hits[0]["external_ref"] == "10/2025-Central Tax"
