"""The idempotency purge as a daily worker job; the purge itself is tested on Postgres."""

from datetime import UTC, datetime, time
from pathlib import Path

import pytest

from py_common.idempotency import purge as purge_module
from py_common.idempotency.purge import JOB_NAME, PURGE_AT, purge_expired_keys, purge_job
from py_common.runtime import IST
from py_common.settings import Settings


def test_a_schema_without_the_table_purges_nothing(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'empty.db'}")
    assert purge_expired_keys(settings) is None


async def test_the_job_runs_the_purge_daily_at_half_past_three_india_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, db_schema="profile")
    purged: list[Settings] = []

    def purge(given: Settings) -> int:
        purged.append(given)
        return 3

    monkeypatch.setattr(purge_module, "purge_expired_keys", purge)
    job = purge_job(settings)
    assert job.name == JOB_NAME
    assert time(3, 30, tzinfo=IST) == PURGE_AT
    assert job.next_run is not None
    evening = datetime(2026, 9, 29, 18, 0, tzinfo=UTC)
    assert job.next_run(evening) == datetime(2026, 9, 30, 3, 30, tzinfo=IST)
    assert await job.run_once() is True
    assert purged == [settings]
    later = purge_job(settings, at=time(4, 0, tzinfo=IST))
    assert later.next_run is not None
    assert later.next_run(evening) == datetime(2026, 9, 30, 4, 0, tzinfo=IST)
