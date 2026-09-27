from datetime import UTC, datetime

from cw_demo.run import main, render, run_demo

NOON_IST = datetime(2026, 9, 28, 6, 30, tzinfo=UTC)


def test_the_demo_walks_from_consent_to_a_reminder() -> None:
    report = run_demo(now=NOON_IST)
    assert report.consents == [
        "terms",
        "privacy_notice",
        "profile_processing",
        "whatsapp_reminders",
    ]
    assert "registration_type" in report.prefilled
    assert report.warnings == []
    assert report.open_questions == 0
    assert report.rules_evaluated >= 13
    assert "gstr3b_monthly" in report.applies
    assert report.unsure == ["itc04_annual"], "a free-text predicate stays unsure"
    assert "gstr9_annual" in report.applies
    assert len(report.obligations) >= 4
    assert report.reminder["outcome"] == "sent"
    assert report.reminder["language"] == "hi"
    assert "STOP" in report.reminder["body"]
    text = render(report)
    assert "needs_review" in text
    assert "obligations materialised" in text


def test_main_exit_code_and_json(capsys: object) -> None:
    assert main(["--daytime"]) == 0
    assert main(["--daytime", "--json"]) == 0
