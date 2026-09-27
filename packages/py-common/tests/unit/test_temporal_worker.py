import pytest

from py_common.temporal.worker import WorkerConfig


def test_worker_config_defaults_and_checks() -> None:
    config = WorkerConfig(task_queue="pipeline")
    assert config.max_concurrent_activities == 20
    assert config.max_concurrent_workflow_tasks == 20
    with pytest.raises(ValueError, match="task_queue"):
        WorkerConfig(task_queue=" ")
    with pytest.raises(ValueError, match="at least 1"):
        WorkerConfig(task_queue="q", max_concurrent_activities=0)
