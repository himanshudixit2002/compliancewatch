"""The eval harness (``evals/harness``, package ``cw_evals``) as the service's suite runner.

The harness runs in a child process through its command line, ``python -m cw_evals``, and its
report, ``latest.json``, is read back from a scratch directory. A child process because the
harness builds the gateway and the services it scores in process with ``create_app``, which
configures logging and telemetry for the whole process: in the service's own process every log
line after a run would carry another service's name. The report's ``gates`` list is the
harness's published output (its README); the exit status only says whether the gates passed,
which the report says too, or that the run stopped before measuring (no report is written).
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from eval_service.domain.errors import EvalHarnessError
from eval_service.domain.model import GateMeasurement, Profile, Suite

HARNESS_COMMAND: Final[tuple[str, ...]] = (sys.executable, "-m", "cw_evals")
REPORT: Final = "latest.json"
DROPPED_ENV: Final = ("GITHUB_STEP_SUMMARY",)
"""The harness appends its Markdown to the GitHub step summary when this names one; a run the
service starts belongs in the service's store only."""


class HarnessSuiteRunner:
    def __init__(
        self,
        *,
        golden_dir: Path,
        gateway_url: str,
        timeout_seconds: float,
        command: Sequence[str] = HARNESS_COMMAND,
    ) -> None:
        self._golden_dir = golden_dir.resolve()
        self._gateway_url = gateway_url
        self._timeout_seconds = timeout_seconds
        self._command = tuple(command)

    def run(self, suite: Suite, profile: Profile) -> Sequence[GateMeasurement]:
        with tempfile.TemporaryDirectory(prefix="cw-eval-") as scratch:
            reports = Path(scratch)
            arguments = [
                *self._command,
                "--profile",
                profile.value,
                "--suite",
                suite.value,
                "--golden",
                str(self._golden_dir),
                "--reports",
                str(reports),
                "--gateway-url",
                self._gateway_url,
            ]
            try:
                finished = subprocess.run(
                    arguments,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    env=_environment(),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise EvalHarnessError(
                    f"the {suite.value} suite did not finish in {self._timeout_seconds:g} seconds"
                ) from exc
            report = reports / REPORT
            if not report.is_file():
                raise EvalHarnessError(
                    f"the {suite.value} suite stopped with exit status {finished.returncode} "
                    f"before measuring its gates: {_last_line(finished.stdout, finished.stderr)}"
                )
            return gates_of(json.loads(report.read_text(encoding="utf-8")))


def gates_of(report: Mapping[str, Any]) -> list[GateMeasurement]:
    """The gates of a harness report, named ``suite.metric[provider]`` (``>=baseline`` added for
    a gate held to another suite's value)."""
    try:
        return [_gate(item) for item in report["gates"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise EvalHarnessError(f"the harness report is not readable: {exc!r}") from exc


def _gate(item: Mapping[str, Any]) -> GateMeasurement:
    name = f"{item['suite']}.{item['metric']}[{item['provider']}]"
    if item.get("baseline"):
        name += f">={item['baseline']}"
    value = item["value"]
    return GateMeasurement(
        name=name,
        metric=str(item["metric"]),
        threshold=float(item["minimum"]),
        value=None if value is None else float(value),
        passed=bool(item["passed"]),
    )


def _environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key not in DROPPED_ENV}
    environment.setdefault("CW_LOG_LEVEL", "WARNING")
    return environment


def _last_line(*outputs: str) -> str:
    """The last line of the first output that has one: the harness says why it stopped on
    stdout, and a crash leaves its traceback on stderr."""
    for output in outputs:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return "no output"
