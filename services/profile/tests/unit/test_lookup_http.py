"""The HTTP GSTIN lookup against an httpx2 MockTransport: mapping, refusals and outages.

Every taxpayer record here is SYNTHETIC: made-up names and values in the shape of the GSTN
taxpayer search, never a real registration and never a recorded provider response."""

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from ontology import load
from profile_service.application.prefill import PrefillFromGstin
from profile_service.application.registration import RegisterNodes
from profile_service.domain.model import ReviewReason
from profile_service.infrastructure.lookup import ManualLookupProvider, StaticLookupProvider
from profile_service.infrastructure.lookup_http import (
    MAPPING_REVIEW_STATUS,
    GstnTaxpayerMapper,
    HttpGstinLookupProvider,
)
from profile_service.infrastructure.memory import MemoryStore
from profile_service.main import _lookup
from profile_service.settings import ProfileSettings
from profile_service.testing import GSTIN_DELHI, GSTIN_KARNATAKA, TENANT, FixedFlags, clock

LOOKUP_URL = "https://gsp.example.test/taxpayers/search"
PROVIDER_KEY = "sandbox"
SYNTHETIC_RECORD: dict[str, Any] = {
    "gstin": GSTIN_KARNATAKA.value,
    "lgnm": "Synthetic Traders Private Limited",
    "tradeNam": "Synthetic  Bengaluru",
    "dty": "Regular",
    "sts": "Active",
    "ctb": "Private Limited Company",
    "rgdt": "01/07/2019",
    "nba": ["Wholesale Business", "Office / Sale Office", "Wholesale Business"],
}
"""SYNTHETIC: a made-up taxpayer record, labelled so; not a provider response."""

type Handler = Callable[[httpx2.Request], httpx2.Response]


def provider(handler: Handler) -> HttpGstinLookupProvider:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return HttpGstinLookupProvider(LOOKUP_URL, api_key=PROVIDER_KEY, client=client)


def answer(status: int, body: object = None) -> Handler:
    def handle(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body)

    return handle


def test_the_mapping_tables_are_marked_for_review() -> None:
    assert MAPPING_REVIEW_STATUS == "needs_review"


def test_a_synthetic_record_maps_to_the_ontology_vocabulary() -> None:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=SYNTHETIC_RECORD)

    result = provider(handle).lookup(GSTIN_KARNATAKA)
    assert result is not None
    assert result.gstin == GSTIN_KARNATAKA
    assert result.legal_name == "Synthetic Traders Private Limited"
    assert result.trade_name == "Synthetic Bengaluru"
    assert (result.registration_type, result.gstin_status, result.constitution) == (
        "regular",
        "active",
        "private_limited",
    )
    assert result.state_code == "29"
    assert result.registered_since == date(2019, 7, 1)
    assert result.nature_of_business == ("Wholesale Business", "Office / Sale Office")
    assert result.business_category == "wholesale_trade"
    request = seen[0]
    assert request.url.params["gstin"] == GSTIN_KARNATAKA.value
    assert str(request.url).startswith(LOOKUP_URL)
    assert request.headers["authorization"] == f"Bearer {PROVIDER_KEY}"


def test_a_record_wrapped_in_data_maps_too() -> None:
    result = provider(answer(200, {"data": SYNTHETIC_RECORD})).lookup(GSTIN_KARNATAKA)
    assert result is not None
    assert result.legal_name == "Synthetic Traders Private Limited"


def test_labels_the_tables_do_not_hold_stay_empty() -> None:
    record = {
        **SYNTHETIC_RECORD,
        "dty": "Something New",
        "sts": "",
        "ctb": "Society/ Club/ Trust/ AOP",
        "rgdt": "2019-07-01",
        "nba": ["Wholesale Business", "Retail Business", "Import"],
    }
    result = GstnTaxpayerMapper().map(GSTIN_KARNATAKA, record)
    assert result is not None
    assert (result.registration_type, result.gstin_status, result.constitution) == ("", "", "")
    assert result.registered_since is None
    assert result.nature_of_business == ("Wholesale Business", "Retail Business", "Import")
    assert result.business_category == "", "two categories: the owner is asked"
    assert result.attribute_values() == {}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"rgdt": "31/02/2020"}, None),
        ({"rgdt": None}, None),
        ({"rgdt": "1/7/2019"}, None),
        ({"rgdt": " 01/07/2019 "}, date(2019, 7, 1)),
    ],
)
def test_the_registration_date_is_day_month_year(
    changes: dict[str, object], expected: date | None
) -> None:
    result = GstnTaxpayerMapper().map(GSTIN_KARNATAKA, {**SYNTHETIC_RECORD, **changes})
    assert result is not None
    assert result.registered_since == expected


@pytest.mark.parametrize("activities", ["Wholesale Business", None, 3])
def test_activities_that_are_not_a_list_map_to_none(activities: object) -> None:
    result = GstnTaxpayerMapper().map(GSTIN_KARNATAKA, {**SYNTHETIC_RECORD, "nba": activities})
    assert result is not None
    assert result.nature_of_business == ()
    assert result.business_category == ""


@pytest.mark.parametrize(
    "payload",
    [
        [SYNTHETIC_RECORD],
        {**SYNTHETIC_RECORD, "lgnm": "  "},
        {**SYNTHETIC_RECORD, "gstin": GSTIN_DELHI.value},
    ],
    ids=["not-an-object", "no-legal-name", "another-gstin"],
)
def test_a_record_that_does_not_map_answers_none_and_logs(payload: object) -> None:
    with capture_logs() as logs:
        assert provider(answer(200, payload)).lookup(GSTIN_KARNATAKA) is None
    assert [entry["event"] for entry in logs] == ["gstin_lookup.malformed"]


def test_a_body_that_is_not_json_answers_none_and_logs() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>maintenance</html>")

    with capture_logs() as logs:
        assert provider(handle).lookup(GSTIN_KARNATAKA) is None
    assert [entry["event"] for entry in logs] == ["gstin_lookup.malformed"]


def test_a_gstin_the_registry_does_not_know_answers_none_quietly() -> None:
    with capture_logs() as logs:
        assert provider(answer(404, {"error": "not found"})).lookup(GSTIN_KARNATAKA) is None
    assert logs == []


@pytest.mark.parametrize(
    ("status", "event"),
    [
        (500, "gstin_lookup.unavailable"),
        (503, "gstin_lookup.unavailable"),
        (401, "gstin_lookup.refused"),
        (429, "gstin_lookup.refused"),
    ],
)
def test_an_outage_or_a_refusal_answers_none_and_logs(status: int, event: str) -> None:
    with capture_logs() as logs:
        assert provider(answer(status, {"error": "x"})).lookup(GSTIN_KARNATAKA) is None
    assert [(entry["event"], entry["status_code"]) for entry in logs] == [(event, status)]


@pytest.mark.parametrize(
    ("error", "event"),
    [
        (httpx2.ReadTimeout("slow"), "gstin_lookup.timeout"),
        (httpx2.ConnectError("refused"), "gstin_lookup.unreachable"),
    ],
)
def test_a_timeout_or_a_transport_error_answers_none_and_logs(error: Exception, event: str) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise error

    with capture_logs() as logs:
        assert provider(handle).lookup(GSTIN_KARNATAKA) is None
    assert [entry["event"] for entry in logs] == [event]


def test_a_timeout_opens_the_verify_registration_task() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    store = MemoryStore()
    registration = RegisterNodes(store, clock=clock).registration(TENANT, GSTIN_KARNATAKA, "Acme")
    prefill = PrefillFromGstin(store, provider(handle), load(), FixedFlags(), clock=clock)
    result = prefill.run(TENANT, registration.node.id)
    assert not result.looked_up
    assert result.applied == ("state_codes",)
    with store(TENANT) as uow:
        tasks = uow.profiles.open_review_tasks(registration.node.id)
    assert [task.reason for task in tasks] == [ReviewReason.VERIFY_REGISTRATION]
    assert [task.id for task in tasks] == [result.review_task]


def settings(**overrides: Any) -> ProfileSettings:
    values: dict[str, Any] = {"_env_file": None, "service_name": "profile"}
    return ProfileSettings(**(values | overrides))


def test_the_http_provider_needs_a_url_and_a_key() -> None:
    with pytest.raises(ValidationError, match="CW_PROFILE_GSTIN_LOOKUP_URL"):
        settings(profile_gstin_lookup="http")
    with pytest.raises(ValidationError, match="CW_PROFILE_GSTIN_LOOKUP_API_KEY"):
        settings(profile_gstin_lookup="http", profile_gstin_lookup_url=LOOKUP_URL)


def test_the_setting_picks_the_provider() -> None:
    chosen = _lookup(
        settings(
            profile_gstin_lookup="http",
            profile_gstin_lookup_url=LOOKUP_URL,
            profile_gstin_lookup_api_key=PROVIDER_KEY,
            profile_gstin_lookup_timeout_seconds=2,
        )
    )
    assert isinstance(chosen, HttpGstinLookupProvider)
    assert isinstance(_lookup(settings(profile_gstin_lookup="static")), StaticLookupProvider)
    assert isinstance(_lookup(settings()), ManualLookupProvider)
