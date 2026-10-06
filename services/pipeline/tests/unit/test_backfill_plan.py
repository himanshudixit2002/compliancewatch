"""The backfill plan names, first, exactly the notifications the seed calendar's rules cite (their
``source.instrument`` and ``source.reference``), each in the window of the year its number
names. The calendar is read as a file: the pipeline imports nothing of the rulebook."""

import re
from pathlib import Path

import yaml

from pipeline.backfill import load_plan
from pipeline.domain.crawl import ref_key

SERVICES = Path(__file__).resolve().parents[3]
PLAN = SERVICES / "pipeline" / "backfill-plan.yaml"
CALENDAR = SERVICES / "rulebook" / "seed" / "gst_calendar.yaml"
CITED = re.compile(r"Notification No\. (\d+/\d{4}-Central Tax)")


def cited_by_the_seed() -> set[str]:
    calendar = yaml.safe_load(CALENDAR.read_text(encoding="utf-8"))
    found: set[str] = set()
    for rule in calendar["rules"]:
        source = rule.get("source") or {}
        for text in (source.get("instrument", ""), source.get("reference", "")):
            found.update(CITED.findall(str(text)))
    return found


def test_the_plan_takes_the_seeds_cited_notifications_first() -> None:
    cited = cited_by_the_seed()
    assert cited, "the seed calendar cites notifications"
    rows = load_plan(PLAN)
    named = [ref for row in rows for ref in row.refs]
    assert {ref_key(ref) for ref in named} == {ref_key(ref) for ref in cited}
    first_open = next(index for index, row in enumerate(rows) if not row.refs)
    assert all(row.refs for row in rows[:first_open]), "the named rows come first"
    for row in rows[:first_open]:
        for ref in row.refs:
            year = int(ref.split("/")[1][:4])
            assert row.since.year == year, ref
            assert row.until is not None
            assert row.until.year == year, ref
