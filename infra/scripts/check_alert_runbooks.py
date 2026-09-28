"""Every alert rule links a runbook that exists (guide section 18).

Reads ``infra/dev/prometheus/alerts.yml``, requires ``annotations.runbook_url`` on every rule,
and checks that the URL ends in ``docs/runbooks/<name>.md`` for a file in the repository.
Exit code 1 lists the offending rules. Run as ``make runbooks-check``.
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ALERTS = ROOT / "infra" / "dev" / "prometheus" / "alerts.yml"
RUNBOOKS = ROOT / "docs" / "runbooks"
MARKER = "docs/runbooks/"


def problems(alerts_path: Path = ALERTS, runbooks_dir: Path = RUNBOOKS) -> list[str]:
    data = yaml.safe_load(alerts_path.read_text(encoding="utf-8"))
    found: list[str] = []
    groups = data.get("groups", []) if isinstance(data, dict) else []
    for group in groups:
        for rule in group.get("rules", []):
            name = rule.get("alert", "<record>")
            url = (rule.get("annotations") or {}).get("runbook_url", "")
            if not url:
                found.append(f"{group.get('name')}/{name}: no runbook_url annotation")
                continue
            _, _, relative = url.partition(MARKER)
            if not relative or not (runbooks_dir / relative).is_file():
                found.append(f"{group.get('name')}/{name}: runbook {url} does not exist")
    if not groups:
        found.append(f"{alerts_path}: no alert groups")
    return found


def main() -> int:
    found = problems()
    for problem in found:
        sys.stderr.write(f"alert runbook check: {problem}\n")
    if found:
        return 1
    sys.stdout.write(
        f"alert runbook check: every rule in {ALERTS.name} links an existing runbook\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
