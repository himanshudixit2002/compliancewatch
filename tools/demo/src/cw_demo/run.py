"""``cw-demo``: onboard a demo business and walk it to its first WhatsApp reminder.

Every service runs in this process with its memory store and its own HTTP API through a test
client: identity records the consents, profile registers the business and pre-fills it from the
static GSTIN lookup, the rulebook's seed calendar is evaluated against the profile snapshot,
the obligation service materialises the calendar, and the notification service renders and
"sends" the first reminder through a fake channel. Nothing leaves the machine. Every rule in
the seed is ``needs_review``: the demo shows the flow, not legal advice.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from cw_demo import tenant as demo
from domain_kernel.channels import Channel
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, NotificationId, RuleId, RuleVersionId
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Applicability
from domain_kernel.rules import RuleVersionSnapshot
from identity.main import build_app as build_identity
from identity.testing import identity_settings
from notification.application.dispatch import DispatchDue
from notification.application.preferences import SetOptIn
from notification.application.receipts import InboundTime, ReconcileReceipts
from notification.application.send import SendNow
from notification.domain.model import NotificationRequest
from notification.domain.preferences import ConsentSource as PreferenceSource
from notification.infrastructure.memory import MemoryStore as NotificationStore
from notification.testing import FakeChannel, FakeRuleVersionReader
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.infrastructure.memory import MemoryStore as ObligationStore
from ontology import load as load_ontology
from profile_service.main import build_app as build_profile
from profile_service.settings import ProfileSettings
from rulebook.application.seed_loader import load_calendar

HEADERS = {"x-tenant-id": str(demo.TENANT_ID)}


@dataclass
class DemoReport:
    consents: list[str] = field(default_factory=list)
    entity_id: str = ""
    registration_id: str = ""
    prefilled: list[str] = field(default_factory=list)
    answered: list[str] = field(default_factory=list)
    open_questions: int = 0
    rules_evaluated: int = 0
    applies: list[str] = field(default_factory=list)
    not_applicable: list[str] = field(default_factory=list)
    unsure: list[str] = field(default_factory=list)
    obligations: list[dict[str, Any]] = field(default_factory=list)
    reminder: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def run_demo(*, now: datetime | None = None) -> DemoReport:
    now = now or datetime.now(UTC)
    report = DemoReport()
    ontology = load_ontology()

    with TestClient(build_identity(identity_settings())) as identity:
        for purpose in ("terms", "privacy_notice", "profile_processing", "whatsapp_reminders"):
            response = identity.post(
                "/v1/identity/consents",
                json={
                    "subject": str(demo.OWNER_ID),
                    "purpose": purpose,
                    "source": "web_onboarding",
                    "notice_version": demo.NOTICE_VERSION,
                    "evidence": "onboarding checkbox (demo)",
                    "recorded_by": str(demo.OWNER_ID),
                },
                headers=HEADERS,
            )
            response.raise_for_status()
            report.consents.append(purpose)

    settings = ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="memory",
        profile_gstin_lookup="static",
    )
    with TestClient(build_profile(settings)) as profile:
        registered = profile.post(
            "/v1/profile/registrations",
            json={
                "gstin": demo.GSTIN,
                "name": demo.REGISTRATION_NAME,
                "entity_name": demo.ENTITY_NAME,
            },
            headers=HEADERS,
        )
        registered.raise_for_status()
        node = registered.json()
        report.registration_id, report.entity_id = node["id"], node["parent_id"]
        prefill = profile.post(
            f"/v1/profile/registrations/{node['id']}/prefill", json={}, headers=HEADERS
        )
        prefill.raise_for_status()
        report.prefilled = list(prefill.json()["applied"])
        fy = FinancialYear.for_date(demo.AS_OF).label
        for key, value in demo.ATTRIBUTES.items():
            level = ontology.require(key).level.value
            target = node["id"] if level == "registration" else node["parent_id"]
            per_fy = ontology.require(key).per_financial_year
            change: dict[str, Any] = {"key": key, "value": value}
            if per_fy:
                change["as_of_fy"] = fy
            answer = profile.put(
                f"/v1/profile/nodes/{target}/attributes",
                json={
                    "changes": [change],
                    "source": "user_input",
                    "changed_by": str(demo.OWNER_ID),
                },
                headers=HEADERS,
            )
            if answer.status_code != 200:
                report.warnings.append(f"{key}: {answer.json().get('detail', answer.text)}")
                continue
            report.answered.append(key)
        pending = profile.get(
            f"/v1/profile/nodes/{node['id']}/next-question",
            params={"as_of_fy": fy},
            headers=HEADERS,
        )
        report.open_questions = 0 if pending.json().get("attribute") is None else 1
        snapshot = profile.get(
            f"/v1/profile/nodes/{node['id']}/snapshot", params={"fy": fy}, headers=HEADERS
        ).json()
    attributes = _attributes(snapshot["attributes"])

    calendar = load_calendar(ontology)
    store = ObligationStore()
    materialise = MaterialiseObligations(store, window=2, clock=lambda: now)
    for rule in calendar.rules:
        report.rules_evaluated += 1
        verdict = rule.specification.evaluate(attributes, ontology)
        if verdict is Applicability.APPLIES:
            report.applies.append(rule.rule_key)
        elif verdict is Applicability.NOT_APPLICABLE:
            report.not_applicable.append(rule.rule_key)
            continue
        else:
            report.unsure.append(rule.rule_key)
            continue
        snapshot_rule = RuleVersionSnapshot(
            rule_id=RuleId.new(),
            rule_version_id=RuleVersionId.new(),
            version=1,
            regulator=rule.regulator,
            title=rule.title,
            specification=rule.specification,
            effective=EffectivePeriod(rule.effective_from),
            obligation_template=rule.obligation_template,
            recurrence=rule.recurrence,
        )
        materialise.run(
            MaterialiseRequest(
                demo.TENANT_ID,
                BusinessId(_uuid(report.registration_id)),
                DecisionId.new(),
                snapshot_rule,
                demo.AS_OF,
            )
        )
    obligations = sorted(store.of_tenant(demo.TENANT_ID), key=lambda o: (o.due_at or now, o.title))
    report.obligations = [
        {
            "title": o.title,
            "period": None if o.period is None else o.period.label,
            "due": None if o.due_at is None else o.due_at.astimezone(UTC).date().isoformat(),
            "steps": list(o.steps),
        }
        for o in obligations
    ]

    notifications = NotificationStore()
    SetOptIn(notifications, clock=lambda: now).run(
        Channel.WHATSAPP,
        demo.OWNER_PHONE,
        opted_in=True,
        source=PreferenceSource.WEB_ONBOARDING,
        language="hi",
    )
    # The owner messaged the business number (the bot forwards the time), which opens WhatsApp's
    # 24-hour window: until Meta approves the templates, free text goes only inside it.
    ReconcileReceipts(notifications, notifications.work_index, clock=lambda: now).run(
        Channel.WHATSAPP, inbound=[InboundTime(demo.OWNER_PHONE, now)]
    )
    channel = FakeChannel(clock=lambda: now)
    dispatch = DispatchDue(
        notifications,
        notifications.work_index,
        {Channel.WHATSAPP: channel},
        rules=FakeRuleVersionReader(),
        web_base_url="http://localhost:3000",
        clock=lambda: now,
    )
    sender = SendNow(notifications, dispatch, clock=lambda: now)
    if obligations:
        first = obligations[0]
        outcome = sender.run(
            NotificationRequest(
                notification_id=NotificationId.new(),
                tenant_id=demo.TENANT_ID,
                obligation_id=first.id,
                business_id=first.business_id,
                channel=Channel.WHATSAPP,
                recipient=demo.OWNER_PHONE,
                template_key="obligation_due_soon",
                params={
                    "business_name": demo.REGISTRATION_NAME,
                    "title": first.title,
                    "due_date": ""
                    if first.due_at is None
                    else first.due_at.astimezone(UTC).date().isoformat(),
                    "steps": "; ".join(first.steps),
                },
            )
        )
        report.reminder = {
            "outcome": outcome.outcome.value,
            "language": outcome.language,
            "scheduled_for": None
            if outcome.scheduled_for is None
            else outcome.scheduled_for.isoformat(),
            "body": channel.sent[0].body if channel.sent else "",
        }
    return report


def _attributes(raw: dict[str, Any]) -> dict[str, object]:
    return {
        key: (frozenset(value) if isinstance(value, list) else value) for key, value in raw.items()
    }


def _uuid(text: str) -> Any:
    from uuid import UUID

    return UUID(text)


def render(report: DemoReport) -> str:
    consents = ", ".join(report.consents)
    prefilled = ", ".join(report.prefilled) or "nothing"
    lines = [
        "# ComplianceWatch demo tenant",
        "",
        "Every rule below is a draft (`seed_status: needs_review`); the demo shows the flow, "
        "not advice.",
        "",
        f"1. Consent recorded for {len(report.consents)} purposes ({consents}) "
        f"under notice {demo.NOTICE_VERSION}.",
        f"2. Registered {demo.REGISTRATION_NAME} ({demo.GSTIN}) under {demo.ENTITY_NAME}; "
        f"the GSTIN lookup pre-filled {prefilled}.",
        f"3. The owner answered {len(report.answered)} questions; "
        f"open questions left: {report.open_questions}.",
        f"4. {report.rules_evaluated} seed rules evaluated: {len(report.applies)} apply, "
        f"{len(report.not_applicable)} do not, {len(report.unsure)} unsure.",
        "   applies: " + (", ".join(report.applies) or "-"),
        "   not applicable: " + (", ".join(report.not_applicable) or "-"),
        "   unsure: " + (", ".join(report.unsure) or "-"),
        f"5. {len(report.obligations)} obligations materialised (each recurring rule's periods "
        "still due, through the next one):",
    ]
    for o in report.obligations:
        lines.append(f"   - {o['due']}  {o['title']}")
    if report.reminder:
        held = report.reminder["scheduled_for"]
        lines += [
            f"6. First reminder on WhatsApp: outcome {report.reminder['outcome']}, "
            f"language {report.reminder['language']}" + (f", held until {held}" if held else ""),
            "   " + (report.reminder["body"] or "(no body: deferred or failed)"),
        ]
    if report.warnings:
        lines += ["", "Warnings:", *[f"- {w}" for w in report.warnings]]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cw-demo", description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--daytime", action="store_true", help="run as if it were noon IST (outside quiet hours)"
    )
    args = parser.parse_args(argv)
    now = datetime(2026, 9, 28, 6, 30, tzinfo=UTC) if args.daytime else None
    report = run_demo(now=now)
    sys.stdout.write(json.dumps(asdict(report), indent=2) if args.json else render(report))
    return 1 if report.warnings or not report.obligations else 0


if __name__ == "__main__":
    raise SystemExit(main())
