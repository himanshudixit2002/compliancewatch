"""``cw-product``: seed, publish, evaluate and check the local product (``make product``).

- ``cw-product seed [--rule KEY]... [--state PATH]``: the synthetic tenants, the demo publication
  (the three GSTR-3B rules unless ``--rule`` names others) and the first decisions; records the
  business tenant for the web app's development sign-in;
- ``cw-product publish [--rule KEY]...``: the demo publication alone, such as
  ``--rule gstr9_annual``, the fourth rule the golden world cites;
- ``cw-product evaluate [--tenant KEY]... [--fresh]``: a decision of every published rule for
  every seeded registration;
- ``cw-product check [--step NAME]... [--timeout SECONDS] [--destructive]``: the check's steps
  in order; the fanout step also reads the database at ``CW_PRODUCT_RECORDS_URL``, read only.
  ``--destructive`` lets the rollback step withdraw gstr9_annual, which only a database made for
  the run can afford (the CI dev-stack job); without it that step reports itself skipped.

Each takes ``--json``. The tool reads ``CW_*`` as the services do and refuses to run unless
``CW_ENV`` is local or test and ``CW_AUTH_MODE`` header or dual (exit 2). A step that fails
exits 1 with what went wrong; ``check`` exits 0 only when every step it ran passed.
"""

import argparse
import dataclasses
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx2

from cw_demo.product import check as checks
from cw_demo.product.client import (
    SERVICE_NAME,
    STATE_PATH,
    Product,
    ProductError,
    ProductSettings,
    refusal,
)
from cw_demo.product.evaluate import Decision, evaluate
from cw_demo.product.publish import DEFAULT_RULES, Publication, publish
from cw_demo.product.records import PostgresRecords
from cw_demo.product.seed import SeedReport, seed
from cw_demo.product.tenants import TENANTS, tenant_named

PROG = "cw-product"
DESCRIPTION = "Seed, publish, evaluate and check the local product (make product)."
NEEDS_REVIEW_NOTE = (
    "Every published version still reads needs_review: the publication is synthetic, not an "
    "analyst's review."
)


def render_publication(publication: Publication) -> list[str]:
    lines = ["Recorded notifications registered:"]
    lines += [
        f"  {document.external_ref:<22} {document.document_id} "
        f"({'registered now' if document.created else 'already there'})"
        for document in publication.documents
    ]
    lines.append("Seed rules published:")
    for rule in publication.rules:
        done = "; ".join(rule.steps) if rule.steps else "already published"
        lines.append(
            f"  {rule.rule_key:<26} v{rule.version} {rule.status}, {rule.seed_status}, "
            f"{rule.citations} verified citations ({done})"
        )
    lines.append(NEEDS_REVIEW_NOTE)
    return lines


def render_decisions(decisions: Sequence[Decision]) -> list[str]:
    if not decisions:
        return ["No decision: nothing is published, or no tenant is seeded yet."]
    lines = ["Decisions:"]
    lines += [
        f"  {d.tenant}/{d.business:<17} {d.rule_key:<26} {d.result}"
        + (" (needs review)" if d.needs_review else "")
        + (" (made earlier today)" if d.replayed else "")
        for d in decisions
    ]
    return lines


def render_seed(report: SeedReport) -> list[str]:
    lines = [f"Seeded at {report.seeded_at}:"]
    for tenant in report.tenants:
        consents = ", ".join(tenant.consents_recorded) or "already recorded"
        lines.append(f"  {tenant.name} ({tenant.kind}, tenant {tenant.tenant_id})")
        lines.append(f"    consents: {consents}")
        for business in tenant.businesses:
            lines.append(
                f"    {business.name}: {business.gstin}, registration {business.registration_id} "
                f"({'created' if business.created else 'found'}), {business.answered} answers"
            )
        lines.append(f"    hears on: {', '.join(tenant.addresses)}")
    lines.append(f"Development sign-in state: {report.state_path}")
    if report.publication is not None:
        lines += render_publication(report.publication)
    lines += render_decisions(report.decisions)
    return lines


def _settings() -> ProductSettings:
    return ProductSettings(service_name=SERVICE_NAME)


def _emit(value: Any, text: Callable[[], list[str]], as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(_plain(value), indent=2) + "\n")
    else:
        sys.stdout.write("\n".join(text()) + "\n")


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def run_seed(product: Product, args: argparse.Namespace) -> int:
    report = seed(product, rules=args.rule or DEFAULT_RULES, state_path=args.state)
    _emit(report, lambda: render_seed(report), args.json)
    return 0


def run_publish(product: Product, args: argparse.Namespace) -> int:
    publication = publish(product, args.rule or DEFAULT_RULES)
    _emit(publication, lambda: render_publication(publication), args.json)
    return 0


def run_evaluate(product: Product, args: argparse.Namespace) -> int:
    tenants = [tenant_named(key) for key in args.tenant] if args.tenant else list(TENANTS)
    decisions = evaluate(product, tenants, fresh=args.fresh)
    _emit(decisions, lambda: render_decisions(decisions), args.json)
    return 0 if decisions else 1


def run_check(product: Product, args: argparse.Namespace) -> int:
    steps = checks.select(args.step)
    url = product.settings.product_records_url
    records = PostgresRecords(url) if url else None
    try:
        context = checks.CheckContext(
            product, timeout=args.timeout, records=records, destructive=args.destructive
        )
        results = checks.run_checks(context, steps)
    finally:
        if records is not None:
            records.close()
    if args.json:
        sys.stdout.write(json.dumps(checks.as_json(results), indent=2) + "\n")
    else:
        sys.stdout.write(checks.render(results))
    return 0 if all(result.ok for result in results) else 1


def _rule_option(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--rule", action="append", metavar="KEY", help="a seed rule to publish; repeatable"
    )


def _json_option(command: argparse.ArgumentParser) -> None:
    command.add_argument("--json", action="store_true", help="print the report as JSON")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog=PROG, description=DESCRIPTION)
    commands = root.add_subparsers(dest="command", required=True)

    seeding = commands.add_parser("seed", help="tenants, the demo publication, first decisions")
    _rule_option(seeding)
    seeding.add_argument(
        "--state", type=Path, default=STATE_PATH, help=f"sign-in state file ({STATE_PATH})"
    )
    _json_option(seeding)
    seeding.set_defaults(run=run_seed)

    publishing = commands.add_parser("publish", help="the demo publication alone")
    _rule_option(publishing)
    _json_option(publishing)
    publishing.set_defaults(run=run_publish)

    evaluating = commands.add_parser("evaluate", help="decide every published rule again")
    evaluating.add_argument(
        "--tenant",
        action="append",
        choices=[tenant.key for tenant in TENANTS],
        help="only this synthetic tenant; repeatable",
    )
    evaluating.add_argument(
        "--fresh", action="store_true", help="new decisions even if made earlier today"
    )
    _json_option(evaluating)
    evaluating.set_defaults(run=run_evaluate)

    checking = commands.add_parser("check", help="prove the product works, step by step")
    checking.add_argument(
        "--step",
        action="append",
        choices=[step.name for step in checks.STEPS],
        help="only this step; repeatable",
    )
    checking.add_argument(
        "--timeout",
        type=float,
        default=checks.TIMEOUT_SECONDS,
        help=f"seconds each wait may take (default {checks.TIMEOUT_SECONDS:.0f})",
    )
    checking.add_argument(
        "--destructive",
        action="store_true",
        help="also run the steps that withdraw seed rules (rollback); only on a throwaway database",
    )
    _json_option(checking)
    checking.set_defaults(run=run_check)
    return root


def main(argv: Sequence[str] | None = None, *, settings: ProductSettings | None = None) -> int:
    args = parser().parse_args(argv)
    chosen = settings or _settings()
    refused = refusal(chosen)
    if refused is not None:
        sys.stderr.write(f"{PROG}: refused: {refused}\n")
        return 2
    run: Callable[[Product, argparse.Namespace], int] = args.run
    try:
        with Product.connect(chosen) as product:
            return run(product, args)
    except ProductError as exc:
        sys.stderr.write(f"{PROG} {args.command}: {exc}\n")
    except httpx2.TransportError as exc:
        sys.stderr.write(
            f"{PROG} {args.command}: cannot reach the product ({type(exc).__name__}: {exc}); "
            "is make product running?\n"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
