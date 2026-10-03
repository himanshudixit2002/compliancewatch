"""Running a suite stores the run and publishes eval.run.completed in one unit of work; the
queries read the stored runs."""

import pytest

from eval_service.application.queries import GetEvalRun, ListEvalRuns, RunQuery
from eval_service.application.run_eval import RunEvalSuite
from eval_service.domain.errors import EvalHarnessError, EvalRunNotFoundError
from eval_service.domain.events import EvalRunCompleted
from eval_service.domain.model import EvalRunId, Profile, Suite
from eval_service.infrastructure.memory import MemoryStore
from eval_service.testing import NOW, ScriptedRunner, TickingClock, gate

RECALL = "relations.relation_recall[scripted]"


def test_a_run_is_stored_with_its_gates_and_published() -> None:
    store = MemoryStore()
    runner = ScriptedRunner([gate(RECALL, 1.0)])
    run = RunEvalSuite(store, runner, clock=TickingClock()).run(Suite.RELATIONS, Profile.CI)

    assert runner.calls == [(Suite.RELATIONS, Profile.CI)]
    assert (run.started_at, run.completed_at) == (NOW, NOW.replace(second=1))
    assert store.runs == {run.id: run}
    (event,) = store.events
    assert isinstance(event, EvalRunCompleted)
    assert event.run_id == run.id
    assert event.passed


def test_drift_is_measured_against_the_last_run_of_the_same_suite_and_profile() -> None:
    store = MemoryStore()
    runner = ScriptedRunner([gate(RECALL, 1.0)], [gate(RECALL, 0.75)], [gate(RECALL, 0.5)])
    use_case = RunEvalSuite(store, runner, clock=TickingClock())
    first = use_case.run(Suite.RELATIONS, Profile.CI)
    other_profile = use_case.run(Suite.RELATIONS, Profile.NIGHTLY)
    second = use_case.run(Suite.RELATIONS, Profile.CI)

    assert other_profile.previous_run_id is None
    assert second.previous_run_id == first.id
    assert second.gates[0].previous_value == 1.0
    assert second.gates[0].drift == -0.5
    assert second.regressed_gates == (RECALL,)
    assert not second.passed


def test_a_harness_failure_stores_and_publishes_nothing() -> None:
    store = MemoryStore()
    use_case = RunEvalSuite(store, ScriptedRunner(failure="no labelled cases"))
    with pytest.raises(EvalHarnessError, match="no labelled cases"):
        use_case.run(Suite.EXTRACTION, Profile.CI)
    assert store.runs == {}
    assert store.events == []


def test_listing_filters_and_orders_latest_first() -> None:
    store = MemoryStore()
    use_case = RunEvalSuite(store, ScriptedRunner(), clock=TickingClock())
    relations = use_case.run(Suite.RELATIONS, Profile.CI)
    qa = use_case.run(Suite.QA, Profile.CI)
    nightly = use_case.run(Suite.QA, Profile.NIGHTLY)
    list_runs = ListEvalRuns(store)

    assert list_runs.run(RunQuery()) == [nightly, qa, relations]
    assert list_runs.run(RunQuery(suite=Suite.QA)) == [nightly, qa]
    assert list_runs.run(RunQuery(profile=Profile.CI)) == [qa, relations]
    assert list_runs.run(RunQuery(limit=1)) == [nightly]


@pytest.mark.parametrize("limit", [0, 101])
def test_a_query_limit_is_between_one_and_a_hundred(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        RunQuery(limit=limit)


def test_getting_a_run() -> None:
    store = MemoryStore()
    run = RunEvalSuite(store, ScriptedRunner()).run(Suite.RELATIONS, Profile.CI)
    assert GetEvalRun(store).run(run.id) == run
    with pytest.raises(EvalRunNotFoundError):
        GetEvalRun(store).run(EvalRunId.new())


def test_a_unit_of_work_that_fails_keeps_nothing() -> None:
    store = MemoryStore()
    run = RunEvalSuite(store, ScriptedRunner()).run(Suite.RELATIONS, Profile.CI)

    def publish_then_fail() -> None:
        with store() as uow:
            uow.events.publish(EvalRunCompleted.of(run))
            raise RuntimeError("rolled back")

    def add_again() -> None:
        with store() as uow:
            uow.runs.add(run)

    with pytest.raises(RuntimeError):
        publish_then_fail()
    with pytest.raises(ValueError, match="duplicate"):
        add_again()
    assert len(store.events) == 1
