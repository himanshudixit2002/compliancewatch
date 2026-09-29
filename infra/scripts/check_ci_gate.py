"""Every job in ci.yml feeds the one required check, ``CI gate``.

Branch protection on main requires the check by that name and no other job of ci.yml. The gate
job needs every other job, runs even when one of them failed (``if: always()``), and passes only
when each result is success or skipped. A job left out of its needs could fail without blocking a
merge; and a gate without ``always()`` would be skipped after a failure, and GitHub counts a
skipped required check as passed. This check fails on either. Exit code 1 lists the problems.
Run as ``make ci-gate-check`` (part of ``make check`` and the ops job).
"""

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
GATE_JOB = "gate"
GATE_NAME = "CI gate"


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    if isinstance(needs, str):
        return [needs]
    return [str(name) for name in needs] if isinstance(needs, list) else []


def problems(workflow: Any) -> list[str]:
    jobs = workflow.get("jobs") if isinstance(workflow, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        return ["the workflow has no jobs"]
    gate = jobs.get(GATE_JOB)
    if not isinstance(gate, dict):
        return [f"no job '{GATE_JOB}': branch protection requires the check '{GATE_NAME}'"]
    found: list[str] = []
    if gate.get("name") != GATE_NAME:
        found.append(
            f"job '{GATE_JOB}' is named {gate.get('name')!r}; branch protection requires "
            f"'{GATE_NAME}'"
        )
    if "always()" not in str(gate.get("if", "")):
        found.append(
            f"job '{GATE_JOB}' does not run with if: always(), so a failed job would skip it "
            "and a skipped required check counts as passed"
        )
    if "needs" not in yaml.safe_dump(gate.get("steps", [])):
        found.append(f"job '{GATE_JOB}' has no step that reads the results of its needs")
    needs = set(_needs(gate))
    for job in sorted(set(jobs) - needs - {GATE_JOB}):
        found.append(
            f"job '{job}' is not in {GATE_JOB}.needs, so its failure would not block a merge"
        )
    return found


def main() -> int:
    found = problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
    for problem in found:
        sys.stderr.write(f"ci gate check: {problem}\n")
    if found:
        return 1
    sys.stdout.write(f"ci gate check: '{GATE_NAME}' needs every other job in {WORKFLOW.name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
