"""The harness runner's handling of the child process, with a stand-in command for the harness:
the report it reads back, a run that stops before measuring, a timeout, an unreadable report."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from eval_service.domain.errors import EvalHarnessError
from eval_service.domain.model import GateMeasurement, Profile, Suite
from eval_service.infrastructure.harness import HarnessSuiteRunner, gates_of

GATES: list[dict[str, Any]] = [
    {"suite": "qa_kag", "metric": "grounded_answer_rate", "provider": "scripted", "minimum": 1.0,
     "baseline": None, "tolerance": 0.0, "value": 1.0, "baseline_value": None, "passed": True},
    {"suite": "qa_kag", "metric": "grounded_answer_rate", "provider": "scripted", "minimum": 0.0,
     "baseline": "qa_hybrid", "tolerance": 0.0, "value": 1.0, "baseline_value": 0.4,
     "passed": True},
    {"suite": "qa_kag", "metric": "response_rate", "provider": "fake", "minimum": 1.0,
     "baseline": None, "tolerance": 0.0, "value": None, "baseline_value": None, "passed": False},
]  # fmt: skip

STAND_IN = """
import json, os, sys, time
args = sys.argv[1:]
reports = args[args.index("--reports") + 1]
with open(os.path.join(os.environ["STAND_IN_DIR"], "argv.json"), "w") as handle:
    json.dump({"argv": args, "summary": os.environ.get("GITHUB_STEP_SUMMARY")}, handle)
mode = os.environ["STAND_IN_MODE"]
if mode == "report":
    with open(os.path.join(reports, "latest.json"), "w") as handle:
        json.dump({"profile": "ci", "gates": json.loads(os.environ["STAND_IN_GATES"])}, handle)
    sys.exit(1)
if mode == "abort":
    print("eval: aborted: a model call the labels do not cover")
    sys.exit(2)
if mode == "garbled":
    with open(os.path.join(reports, "latest.json"), "w") as handle:
        json.dump({"profile": "ci"}, handle)
    sys.exit(0)
time.sleep(5)
"""


@pytest.fixture
def stand_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "harness.py"
    script.write_text(STAND_IN, encoding="utf-8")
    monkeypatch.setenv("STAND_IN_DIR", str(tmp_path))
    monkeypatch.setenv("STAND_IN_GATES", json.dumps(GATES))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    return script


def runner(script: Path, timeout: float = 30.0) -> HarnessSuiteRunner:
    return HarnessSuiteRunner(
        golden_dir=Path("evals/golden"),
        gateway_url="http://gateway.test",
        timeout_seconds=timeout,
        command=(sys.executable, str(script)),
    )


def test_the_report_gates_come_back_named_by_suite_metric_and_provider(
    stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STAND_IN_MODE", "report")
    gates = runner(stand_in).run(Suite.QA, Profile.NIGHTLY)
    assert gates == [
        GateMeasurement("qa_kag.grounded_answer_rate[scripted]", "grounded_answer_rate", 1.0,
                        1.0, True),
        GateMeasurement("qa_kag.grounded_answer_rate[scripted]>=qa_hybrid",
                        "grounded_answer_rate", 0.0, 1.0, True),
        GateMeasurement("qa_kag.response_rate[fake]", "response_rate", 1.0, None, False),
    ]  # fmt: skip
    called = json.loads((stand_in.parent / "argv.json").read_text(encoding="utf-8"))
    argv = called["argv"]
    assert argv[argv.index("--profile") + 1] == "nightly"
    assert argv[argv.index("--suite") + 1] == "qa"
    assert argv[argv.index("--gateway-url") + 1] == "http://gateway.test"
    assert Path(argv[argv.index("--golden") + 1]).is_absolute()
    assert called["summary"] is None, "the GitHub step summary is not the service's to write"


def test_a_run_that_stops_before_measuring_is_a_harness_error(
    stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STAND_IN_MODE", "abort")
    with pytest.raises(EvalHarnessError, match=r"exit status 2.*a model call the labels"):
        runner(stand_in).run(Suite.QA, Profile.CI)


def test_an_unreadable_report_is_a_harness_error(
    stand_in: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STAND_IN_MODE", "garbled")
    with pytest.raises(EvalHarnessError, match="not readable"):
        runner(stand_in).run(Suite.QA, Profile.CI)


def test_a_run_past_the_timeout_is_stopped(stand_in: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_IN_MODE", "sleep")
    with pytest.raises(EvalHarnessError, match=r"did not finish in 0\.5 seconds"):
        runner(stand_in, timeout=0.5).run(Suite.EXTRACTION, Profile.CI)


def test_a_crash_names_its_last_line() -> None:
    crashing = HarnessSuiteRunner(
        golden_dir=Path("evals/golden"),
        gateway_url="http://gateway.test",
        timeout_seconds=30,
        command=(sys.executable, "-c", "raise SystemExit('boom')"),
    )
    with pytest.raises(EvalHarnessError, match="exit status 1 before measuring its gates: boom"):
        crashing.run(Suite.RELATIONS, Profile.CI)


def test_a_silent_failure_says_so() -> None:
    silent = HarnessSuiteRunner(
        golden_dir=Path("evals/golden"),
        gateway_url="http://gateway.test",
        timeout_seconds=30,
        command=(sys.executable, "-c", "raise SystemExit(3)"),
    )
    with pytest.raises(EvalHarnessError, match="no output"):
        silent.run(Suite.RELATIONS, Profile.CI)


def test_a_gate_with_a_bad_value_is_unreadable() -> None:
    with pytest.raises(EvalHarnessError, match="not readable"):
        gates_of({"gates": [{**GATES[0], "value": "high"}]})
