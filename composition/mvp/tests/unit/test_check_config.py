"""``cw-mvp check-config``: every rule, the settings classes' own and the staging and production
ones on top of them."""

import os
from typing import Any

import pytest

from cw_mvp.check_config import SHARED, ConfigReport, Problem, check
from cw_mvp.cli import main
from cw_mvp.registry import REGISTRY, ServiceEntry

STAGING: dict[str, str] = {
    "CW_ENV": "staging",
    "CW_AUTH_MODE": "dual",
    "CW_IDENTITY_SIGNING_KEYS": "signing-keys-of-the-check",
    "CW_AUTH_PROVIDER": "supabase",
    "CW_SUPABASE_URL": "https://project.supabase.invalid",
    "CW_SUPABASE_SERVICE_ROLE_KEY": "service-role-of-the-check",
    "CW_LLM_PROVIDER": "vercel",
    "CW_AI_GATEWAY_API_KEY": "gateway-key-of-the-check",
    "CW_LLM_LEDGER": "postgres",
    "CW_PIPELINE_RAW_STORE": "s3",
    "CW_PIPELINE_RAW_BUCKET": "cw-raw-staging",
    "CW_PIPELINE_RAW_ACCESS_KEY_ID": "raw-key-of-the-check",
    "CW_PIPELINE_RAW_SECRET_ACCESS_KEY": "raw-secret-of-the-check",
}
"""A staging environment with nothing to refuse."""
PRODUCTION = STAGING | {"CW_ENV": "prod", "CW_AUTH_MODE": "token"}
STORES = [entry for entry in REGISTRY if entry.store_field is not None]


@pytest.fixture(autouse=True)
def no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only what a test sets: no CW_* of the developer's shell, and no .env (``_env_file``)."""
    for name in list(os.environ):
        if name.startswith("CW_"):
            monkeypatch.delenv(name)


def report(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, str], **changes: str | None
) -> ConfigReport:
    """The check of ``base`` with ``changes`` (``CW_`` dropped from their names; None unsets)."""
    values: dict[str, str | None] = {**base}
    values.update({f"CW_{name.upper()}": value for name, value in changes.items()})
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return check({"_env_file": None})


def lines(found: ConfigReport) -> list[str]:
    return [f"{problem.where}: {problem.message}" for problem in found.problems]


def only(found: ConfigReport) -> Problem:
    assert len(found.problems) == 1, lines(found)
    return found.problems[0]


# ---------------------------------------------------------------- clean environments


def test_local_and_test_take_the_local_conveniences(monkeypatch: pytest.MonkeyPatch) -> None:
    local = {"CW_LLM_PROVIDER": "fake", "CW_NOTIFICATION_CHANNELS": "sink"}
    for env in ("local", "test"):
        found = report(monkeypatch, local, env=env, obligation_store="memory")
        assert found.ok, lines(found)
        assert found.lines() == [f"check-config: CW_ENV={env}, 10 services: no problems"]


@pytest.mark.parametrize("base", [STAGING, PRODUCTION], ids=["staging", "prod"])
def test_a_ready_environment_has_no_problem(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, str]
) -> None:
    found = report(monkeypatch, base)
    assert found.ok, lines(found)
    assert found.env == base["CW_ENV"]


# ---------------------------------------------------------------- the settings classes' rules


def test_production_refuses_header_mode_and_still_checks_the_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found = report(monkeypatch, PRODUCTION, auth_mode="header", llm_provider="fake")
    assert lines(found) == [
        "shared: CW_ENV=prod needs CW_AUTH_MODE=token, got header: production serves no "
        "request without a verified access token",
        "llm-gateway: CW_LLM_PROVIDER=fake answers from a fake model; CW_ENV=prod needs vercel "
        "with CW_AI_GATEWAY_API_KEY",
    ]


def test_production_refuses_the_fake_sign_in_in_identitys_words_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found = report(monkeypatch, PRODUCTION, auth_provider="fake")
    assert only(found) == Problem(
        "identity", "CW_ENV=prod needs CW_AUTH_PROVIDER=supabase: the fake provider signs anyone in"
    )


@pytest.mark.parametrize(
    ("changes", "where", "says"),
    [
        (
            {"identity_signing_keys": None},
            "identity",
            "CW_ENV=staging needs CW_IDENTITY_SIGNING_KEYS",
        ),
        (
            {"identity_dev_client_secret": "a-dev-client-secret-of-at-least-32-chars"},
            "identity",
            "CW_IDENTITY_DEV_CLIENT_SECRET is for local and test only",
        ),
        ({"supabase_url": None}, "identity", "CW_AUTH_PROVIDER=supabase needs CW_SUPABASE_URL"),
        ({"notification_channels": "sink"}, "notification", "CW_NOTIFICATION_CHANNELS=sink"),
        (
            {"rulebook_seed_on_start": "true", "rulebook_store": "memory"},
            "rulebook",
            "CW_RULEBOOK_SEED_ON_START is refused with CW_ENV=staging",
        ),
        ({"ai_gateway_api_key": None}, "llm-gateway", "CW_AI_GATEWAY_API_KEY is required"),
        ({"profile_gstin_lookup": "http"}, "profile", "CW_PROFILE_GSTIN_LOOKUP=http needs"),
        ({"llm_provider": "openai"}, "llm-gateway", "CW_LLM_PROVIDER: Input should be"),
    ],
)
def test_each_settings_class_refuses_in_its_own_words(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str | None], where: str, says: str
) -> None:
    found = report(monkeypatch, STAGING, **changes)
    assert any(p.where == where and says in p.message for p in found.problems), lines(found)


def test_shared_settings_it_cannot_read_end_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    found = report(monkeypatch, STAGING, kafka_security_protocol="SASL_SSL")
    assert found.env is None
    assert only(found).where == SHARED
    assert (
        "CW_KAFKA_SECURITY_PROTOCOL=SASL_SSL needs CW_KAFKA_SASL_MECHANISM" in only(found).message
    )
    assert found.lines()[0] == "check-config: the shared settings: 1 problem"


# ---------------------------------------------------------------- staging and production


@pytest.mark.parametrize(("mode", "ok"), [("header", False), ("dual", True), ("token", True)])
def test_staging_runs_dual_or_token(monkeypatch: pytest.MonkeyPatch, mode: str, ok: bool) -> None:
    found = report(monkeypatch, STAGING, auth_mode=mode)
    assert found.ok is ok
    if not ok:
        assert only(found).message.startswith("CW_ENV=staging needs CW_AUTH_MODE dual or token")


@pytest.mark.parametrize("base", [STAGING, PRODUCTION], ids=["staging", "prod"])
def test_the_fake_model_is_refused(monkeypatch: pytest.MonkeyPatch, base: dict[str, str]) -> None:
    found = report(monkeypatch, base, llm_provider="fake", ai_gateway_api_key=None)
    assert only(found).where == "llm-gateway"
    assert only(found).message.startswith("CW_LLM_PROVIDER=fake answers from a fake model")


def test_staging_refuses_the_fake_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    found = report(monkeypatch, STAGING, auth_provider="fake")
    assert only(found) == Problem(
        "identity",
        "CW_AUTH_PROVIDER=fake signs anyone in; CW_ENV=staging needs supabase, as production does",
    )


def test_the_demo_gstin_table_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    found = report(monkeypatch, STAGING, profile_gstin_lookup="static")
    assert only(found).where == "profile"
    assert only(found).message.startswith("CW_PROFILE_GSTIN_LOOKUP=static pre-fills from the demo")


def test_memory_billing_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    found = report(monkeypatch, PRODUCTION, billing_provider="memory")
    assert only(found).message.startswith("CW_BILLING_PROVIDER=memory is a fake billing provider")


@pytest.mark.parametrize("entry", STORES, ids=lambda entry: entry.name)
def test_every_memory_store_is_refused(
    monkeypatch: pytest.MonkeyPatch, entry: ServiceEntry[Any]
) -> None:
    field = str(entry.store_field)
    found = report(monkeypatch, STAGING, **{field: "memory"})
    assert only(found).where == entry.name
    assert only(found).message.startswith(f"CW_{field.upper()}=memory keeps the service's state")


def test_the_memory_ledger_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    found = report(monkeypatch, PRODUCTION, llm_ledger="memory")
    assert only(found).message.startswith("CW_LLM_LEDGER=memory forgets the spend")


def test_a_rulebook_that_would_take_synthetic_approvals_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rulebook.settings.SYNTHETIC_ENVIRONMENTS", frozenset({"staging"}))
    found = report(monkeypatch, STAGING)
    assert only(found) == Problem(
        "rulebook",
        "the rulebook accepts synthetic approvals with CW_ENV=staging; only local and test may, "
        "where the demo publication sends them",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("rulebook_write_token", "local-write-token"),
        ("rulebook_review_token", "local-review-token"),
    ],
)
def test_the_dev_stacks_rulebook_tokens_are_refused(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    found = report(monkeypatch, STAGING, **{name: value})
    variable = f"CW_{name.upper()}"
    assert only(found) == Problem(
        "rulebook",
        f"{variable} is the placeholder {value}, which the dev stack uses; CW_ENV=staging needs "
        "its own secret",
    )


def test_a_dev_only_secret_is_refused_without_printing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    found = report(monkeypatch, PRODUCTION, notification_bot_token="bot-DEV-ONLY-value-7")
    assert only(found).where == "notification"
    assert only(found).message.startswith("CW_NOTIFICATION_BOT_TOKEN holds a dev-only placeholder")
    assert "bot-DEV-ONLY-value-7" not in "\n".join(found.lines())


def test_a_shared_secret_placeholder_is_reported_once_as_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found = report(monkeypatch, STAGING, service_client_secret="dev-only-worker-secret")
    assert only(found).where == SHARED
    assert only(found).message.startswith("CW_SERVICE_CLIENT_SECRET holds a dev-only placeholder")


def test_whatsapp_needs_its_number_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    found = report(monkeypatch, STAGING, whatsapp_enabled="true")
    assert only(found).message.startswith(
        "CW_WHATSAPP_ENABLED needs CW_WHATSAPP_PHONE_NUMBER_ID, CW_WHATSAPP_ACCESS_TOKEN:"
    )
    ready = report(
        monkeypatch,
        STAGING,
        whatsapp_enabled="true",
        whatsapp_phone_number_id="1234",
        whatsapp_access_token="whatsapp-token-of-the-check",
    )
    assert ready.ok, lines(ready)


def test_email_needs_its_host_sender_password_and_feedback_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found = report(monkeypatch, PRODUCTION, email_enabled="true", smtp_username="mailer")
    assert only(found).message.startswith(
        "CW_EMAIL_ENABLED needs CW_SMTP_HOST, CW_EMAIL_FROM, "
        "CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN, CW_SMTP_PASSWORD:"
    )
    ready = report(
        monkeypatch,
        PRODUCTION,
        email_enabled="true",
        smtp_host="smtp.mail.invalid",
        email_from="alerts@mail.invalid",
        notification_email_feedback_token="feedback-of-the-check",
        smtp_username=None,
    )
    assert ready.ok, lines(ready)


def test_razorpay_needs_its_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    found = report(monkeypatch, STAGING, billing_provider="razorpay", razorpay_key_id="rzp_key")
    assert only(found).message.startswith(
        "CW_BILLING_PROVIDER=razorpay needs CW_RAZORPAY_KEY_SECRET, CW_RAZORPAY_WEBHOOK_SECRET:"
    )


@pytest.mark.parametrize(("mode", "refused"), [("dual", True), ("token", False)])
def test_publishing_needs_the_review_token_outside_token_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, refused: bool
) -> None:
    found = report(monkeypatch, STAGING, auth_mode=mode, rulebook_publish_enabled="true")
    assert found.ok is not refused
    if refused:
        assert only(found).message.startswith(
            "CW_RULEBOOK_PUBLISH_ENABLED in dual mode needs CW_RULEBOOK_REVIEW_TOKEN"
        )


@pytest.mark.parametrize(("mode", "refused"), [("dual", True), ("token", False)])
def test_the_pipeline_needs_the_write_token_outside_token_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, refused: bool
) -> None:
    found = report(monkeypatch, STAGING, auth_mode=mode, pipeline_knowledge_enabled="true")
    assert found.ok is not refused
    if refused:
        assert only(found).where == "pipeline"
        assert only(found).message.startswith(
            "CW_PIPELINE_KNOWLEDGE_ENABLED in dual mode needs CW_RULEBOOK_WRITE_TOKEN"
        )


@pytest.mark.parametrize("base", [STAGING, PRODUCTION], ids=["staging", "prod"])
@pytest.mark.parametrize("store", ["local", "memory"])
def test_the_worker_fetches_documents_only_into_s3(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, str], store: str
) -> None:
    fetching = {"worker_temporal_enabled": "true", "service_client_secret": "worker-secret-x"}
    found = report(monkeypatch, base, pipeline_raw_store=store, **fetching)
    assert only(found).where == "pipeline"
    assert only(found).message.startswith(f"CW_PIPELINE_RAW_STORE={store} keeps the regulator")
    assert only(found).message.endswith(
        "needs s3 while CW_WORKER_TEMPORAL_ENABLED has the worker fetch documents"
    )
    idle = report(monkeypatch, base, pipeline_raw_store=store, worker_temporal_enabled="false")
    assert idle.ok, lines(idle)
    s3 = report(monkeypatch, base, pipeline_raw_store="s3", **fetching)
    assert s3.ok, lines(s3)


@pytest.mark.parametrize("base", [STAGING, PRODUCTION], ids=["staging", "prod"])
def test_the_crawl_flag_fetches_documents_too(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, str]
) -> None:
    crawling = report(monkeypatch, base, pipeline_raw_store="local", pipeline_crawl_enabled="true")
    assert only(crawling).where == "pipeline"
    assert only(crawling).message.endswith(
        "needs s3 while CW_PIPELINE_CRAWL_ENABLED has the worker fetch documents"
    )
    both = report(
        monkeypatch,
        base,
        pipeline_raw_store="local",
        pipeline_crawl_enabled="true",
        worker_temporal_enabled="true",
        service_client_secret="worker-secret-x",
    )
    assert only(both).message.endswith(
        "while CW_WORKER_TEMPORAL_ENABLED and CW_PIPELINE_CRAWL_ENABLED have the worker fetch "
        "documents"
    )
    on_s3 = report(monkeypatch, base, pipeline_raw_store="s3", pipeline_crawl_enabled="true")
    assert on_s3.ok, lines(on_s3)


@pytest.mark.parametrize("base", [STAGING, PRODUCTION], ids=["staging", "prod"])
def test_the_extraction_needs_the_knowledge_flag(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, str]
) -> None:
    alone = report(monkeypatch, base, pipeline_extraction_enabled="true")
    assert only(alone).where == "pipeline"
    assert only(alone).message.startswith(
        "CW_PIPELINE_EXTRACTION_ENABLED needs CW_PIPELINE_KNOWLEDGE_ENABLED"
    )
    both = report(
        monkeypatch,
        base,
        pipeline_extraction_enabled="true",
        pipeline_knowledge_enabled="true",
        rulebook_write_token="a-long-write-token-for-the-check",
    )
    assert both.ok, lines(both)


def test_local_and_test_may_fetch_into_a_local_raw_store(monkeypatch: pytest.MonkeyPatch) -> None:
    local = {"CW_LLM_PROVIDER": "fake", "CW_WORKER_TEMPORAL_ENABLED": "true"}
    found = report(monkeypatch, local, env="local", pipeline_raw_store="local")
    assert found.ok, lines(found)


@pytest.mark.parametrize(
    ("changes", "says"),
    [
        ({"pipeline_raw_bucket": None}, "CW_PIPELINE_RAW_STORE=s3 needs CW_PIPELINE_RAW_BUCKET"),
        ({"pipeline_raw_encryption": "none"}, "CW_PIPELINE_RAW_ENCRYPTION=none stores"),
    ],
)
def test_the_s3_raw_store_is_checked_in_the_pipelines_words(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str | None], says: str
) -> None:
    found = report(monkeypatch, STAGING, **changes)
    assert only(found).where == "pipeline"
    assert says in only(found).message


@pytest.mark.parametrize("switch", ["worker_kafka_enabled", "worker_temporal_enabled"])
def test_token_mode_needs_the_workers_client_secret(
    monkeypatch: pytest.MonkeyPatch, switch: str
) -> None:
    found = report(monkeypatch, PRODUCTION, **{switch: "true"})
    assert only(found).where == SHARED
    assert only(found).message.startswith(
        "CW_AUTH_MODE=token with the worker's Kafka or Temporal switch on needs "
        "CW_SERVICE_CLIENT_SECRET"
    )
    ready = report(
        monkeypatch, PRODUCTION, **{switch: "true", "service_client_secret": "worker-secret-x"}
    )
    assert ready.ok, lines(ready)
    dual = report(monkeypatch, STAGING, **{switch: "true", "service_client_secret": None})
    assert dual.ok, lines(dual)


# ---------------------------------------------------------------- the command


def test_the_command_lists_the_problems_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("cw_mvp.release.check", lambda: check({"_env_file": None}))
    for name, value in (STAGING | {"CW_LLM_PROVIDER": "fake"}).items():
        monkeypatch.setenv(name, value)
    assert main(["check-config"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "check-config: CW_ENV=staging: 1 problem"
    assert out[1].startswith("  llm-gateway: CW_LLM_PROVIDER=fake")

    monkeypatch.setenv("CW_LLM_PROVIDER", "vercel")
    assert main(["check-config"]) == 0
    assert capsys.readouterr().out == "check-config: CW_ENV=staging, 10 services: no problems\n"
