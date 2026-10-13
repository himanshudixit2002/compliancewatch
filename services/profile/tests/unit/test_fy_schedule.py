"""The financial year schedule behind the flag ``profile.fy_schedule``: on the memory store with
a frozen clock it confirms every tenant the directory lists for the year of that moment in India,
once; a tenant that fails is logged and the others go on; the worker hosts the job only with the
flag on, once a day at 00:30 IST."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import ontology as ontology_package
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Pan
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import Ontology
from profile_service.application.attributes import ConfirmFinancialYear, SetAttributes
from profile_service.application.fy_schedule import FinancialYearSchedule
from profile_service.application.registration import RegisterNodes
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange
from profile_service.infrastructure.memory import MemoryStore, MemoryTenantDirectory
from profile_service.settings import ProfileSettings
from profile_service.worker import FY_SCHEDULE_JOB, fy_schedule
from py_common.runtime import IST

FIRST_MINUTE_OF_APRIL_IST = datetime(2027, 3, 31, 18, 30, tzinfo=UTC)
"""00:00 IST on 1 April 2027, still 31 March in UTC: financial year 2027-28."""
TRADERS, STORES, EMPTY = TenantId.new(), TenantId.new(), TenantId.new()


def settings(**overrides: Any) -> ProfileSettings:
    """Settings that ignore the repo ``.env``; the memory store unless told otherwise."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "profile",
        "profile_store": "memory",
    }
    values.update(overrides)
    return ProfileSettings(**values)


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


def april() -> datetime:
    return FIRST_MINUTE_OF_APRIL_IST


def populated(ontology: Ontology) -> MemoryStore:
    """Two tenants with an entity each, one of which answered its 2027-28 turnover band."""
    store = MemoryStore()
    register = RegisterNodes(store, clock=april)
    register.entity(TRADERS, Pan("ABCDE1234F"), "Example Traders")
    stores = register.entity(STORES, Pan("ZZZZZ9999Z"), "Example Stores").node
    SetAttributes(store, ontology, clock=april).run(
        STORES,
        stores.id,
        [AttributeChange("turnover_band", "upto_10_lakh", as_of_fy=FinancialYear(2027))],
        source=ChangeSource.USER_INPUT,
    )
    return store


def test_with_a_frozen_april_clock_the_job_opens_each_tenant_s_tasks_once(
    ontology: Ontology,
) -> None:
    store = populated(ontology)
    schedule = FinancialYearSchedule(
        ConfirmFinancialYear(store, ontology, clock=april),
        MemoryTenantDirectory(store),
        clock=april,
    )
    first = schedule.run()
    assert first.fy == FinancialYear(2027)
    assert first.tenants == 2
    assert set(first.opened) == {TRADERS}, "the other tenant answered the year already"
    assert first.tasks_opened == 1
    assert first.failed == ()
    second = schedule.run()
    assert (second.tenants, second.opened, second.tasks_opened) == (2, {}, 0)
    with store(TRADERS) as uow:
        tasks = uow.profiles.open_review_tasks()
    assert [(task.attribute_key, task.as_of_fy) for task in tasks] == [
        ("turnover_band", FinancialYear(2027))
    ]
    with store(STORES) as uow:
        assert uow.profiles.open_review_tasks() == []
    last_evening_of_march = FIRST_MINUTE_OF_APRIL_IST - timedelta(minutes=1)
    earlier = FinancialYearSchedule(
        ConfirmFinancialYear(store, ontology, clock=april),
        MemoryTenantDirectory(store),
        clock=lambda: last_evening_of_march,
    ).run()
    assert earlier.fy == FinancialYear(2026), "still the old year a minute before"


def test_a_tenant_that_fails_is_reported_and_the_others_go_on(ontology: Ontology) -> None:
    store = populated(ontology)
    failures: list[tuple[TenantId, Exception]] = []

    class Flaky(ConfirmFinancialYear):
        def run(self, tenant_id: TenantId, fy: FinancialYear) -> tuple[BusinessId, ...]:
            if tenant_id == STORES:
                raise RuntimeError("Example: the tenant's unit of work failed")
            return super().run(tenant_id, fy)

    schedule = FinancialYearSchedule(
        Flaky(store, ontology, clock=april),
        MemoryTenantDirectory(store),
        clock=april,
        on_failure=lambda tenant, exc: failures.append((tenant, exc)),
    )
    run = schedule.run()
    assert run.failed == (STORES,)
    assert set(run.opened) == {TRADERS}
    assert [tenant for tenant, _ in failures] == [STORES]
    assert isinstance(failures[0][1], RuntimeError)


def test_the_worker_hosts_the_job_only_with_the_flag_on(ontology: Ontology) -> None:
    store = MemoryStore()
    off = settings(profile_store="postgres")
    assert fy_schedule(off, unit_of_work=store, directory=MemoryTenantDirectory(store)) is None
    on = settings(profile_store="postgres", profile_fy_schedule_enabled=True)
    job = fy_schedule(
        on,
        unit_of_work=store,
        directory=MemoryTenantDirectory(store),
        ontology=ontology,
        clock=april,
    )
    assert job is not None
    assert (job.name, job.interval_seconds) == (FY_SCHEDULE_JOB, None)
    assert job.next_run is not None
    due = job.next_run(FIRST_MINUTE_OF_APRIL_IST)
    assert due.astimezone(IST).strftime("%Y-%m-%d %H:%M") == "2027-04-01 00:30"
    run: Any = job.fn()
    assert run.fy == FinancialYear(2027)
    assert run.tenants == 0, "no tenant has a node yet"
