"""The GSTIN lookup over HTTP: a GSP's or an aggregator's taxpayer search
(``CW_PROFILE_GSTIN_LOOKUP=http``).

``HttpGstinLookupProvider`` sends ``GET <CW_PROFILE_GSTIN_LOOKUP_URL>?gstin=<GSTIN>`` with the key
``CW_PROFILE_GSTIN_LOOKUP_API_KEY`` as a bearer token, and ``GstnTaxpayerMapper`` turns the
answer into a ``GstinLookupResult``. A 404 means the registry has no such GSTIN and answers None.
A timeout, a transport error, a 5xx, any other refusal or a body that does not map also answers
None and logs one line; the prefill then opens a ``verify_registration`` review task, as it does
with no provider at all, so onboarding never waits on the provider.

The provider is not chosen yet (a GSP or an aggregator; an account the maintainer opens). Until
its sandbox has been seen, the request shape, the field names of the GSTN taxpayer search that the
mapper reads (``lgnm``, ``tradeNam``, ``dty``, ``sts``, ``ctb``, ``rgdt``, ``nba``) and the label
tables below are unverified, marked ``needs_review`` in ``MAPPING_REVIEW_STATUS``. A label the
tables do not hold stays empty rather than guessed, and ``business_category`` is written only
behind the flag ``profile.gstin_category_prefill``.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Final

import httpx2

from domain_kernel.identifiers import Gstin
from profile_service.domain.lookup import GstinLookupResult, single_category
from py_common.logging import get_logger

log = get_logger(__name__)

MAPPING_REVIEW_STATUS: Final = "needs_review"
"""Set to ``reviewed`` once the field names and tables are checked against the provider's
sandbox responses."""
GSTIN_PARAMETER: Final = "gstin"
DATE_PATTERN: Final = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
"""The registration date as the taxpayer search writes it: day, month, year (01/07/2017)."""

REGISTRATION_TYPES: Final[Mapping[str, str]] = {
    "regular": "regular",
    "composition": "composition",
    "casual taxable person": "casual",
    "non resident taxable person": "non_resident",
    "input service distributor (isd)": "isd",
    "tax deductor": "tds",
    "tax collector (electronic commerce operator)": "tcs",
    "sez unit": "sez_unit",
    "sez developer": "sez_developer",
}
"""Taxpayer type (``dty``) to the ontology's ``registration_type``; needs review."""
GSTIN_STATUSES: Final[Mapping[str, str]] = {
    "active": "active",
    "suspended": "suspended",
    "cancelled": "cancelled",
    "inactive": "inactive",
}
"""Registration status (``sts``) to the ontology's ``gstin_status``; needs review."""
CONSTITUTIONS: Final[Mapping[str, str]] = {
    "proprietorship": "proprietorship",
    "partnership": "partnership",
    "limited liability partnership": "llp",
    "private limited company": "private_limited",
    "public limited company": "public_limited",
    "hindu undivided family": "huf",
    "government department": "government",
}
"""Constitution of business (``ctb``) to the ontology's ``constitution``; needs review. A label
that covers several of the ontology's values (a trust, a society and an association of persons
share one on the portal) is left out, so the owner is asked."""
CATEGORIES: Final[Mapping[str, str]] = {
    "factory / manufacturing": "manufacturing",
    "wholesale business": "wholesale_trade",
    "retail business": "retail_trade",
    "supplier of services": "services",
    "works contract": "works_contract",
}
"""Nature of business activity (``nba``) to the ontology's ``business_category``; needs review.
Activities that name a kind of premises or a flow of goods (an office, a warehouse, imports)
say nothing about the main activity and are not mapped."""


def _label(value: object) -> str:
    """A portal label compared without case and with single spaces."""
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


class GstnTaxpayerMapper:
    """Maps one taxpayer-search record to a ``GstinLookupResult``."""

    def map(self, gstin: Gstin, payload: object) -> GstinLookupResult | None:
        """The result for ``gstin``, or None when the record has no legal name or names another
        GSTIN. The record is the body itself or, when the provider wraps it, its ``data``."""
        record = _record(payload)
        if record is None:
            return None
        named = _text(record.get("gstin")).upper()
        legal_name = _text(record.get("lgnm"))
        if (named and named != gstin.value) or not legal_name:
            return None
        activities = _activities(record.get("nba"))
        return GstinLookupResult(
            gstin=gstin,
            legal_name=legal_name,
            trade_name=_text(record.get("tradeNam")),
            registration_type=REGISTRATION_TYPES.get(_label(record.get("dty")), ""),
            gstin_status=GSTIN_STATUSES.get(_label(record.get("sts")), ""),
            state_code=gstin.state_code,
            constitution=CONSTITUTIONS.get(_label(record.get("ctb")), ""),
            registered_since=_date(record.get("rgdt")),
            nature_of_business=activities,
            business_category=single_category(
                CATEGORIES.get(_label(activity), "") for activity in activities
            ),
        )


def _record(payload: object) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    return data if isinstance(data, Mapping) else payload


def _activities(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        return ()
    return tuple(dict.fromkeys(text for item in value if (text := _text(item))))


def _date(value: object) -> date | None:
    matched = DATE_PATTERN.fullmatch(_text(value))
    if matched is None:
        return None
    day, month, year = (int(part) for part in matched.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


class HttpGstinLookupProvider:
    """``url`` is ``CW_PROFILE_GSTIN_LOOKUP_URL`` and ``api_key`` the provider's key. Pass
    ``client`` to answer from a transport of the test's own instead of the network."""

    def __init__(
        self,
        url: str,
        *,
        api_key: str,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 5.0,
        mapper: GstnTaxpayerMapper | None = None,
    ) -> None:
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx2.Client(timeout=timeout_seconds)
        self._mapper = mapper or GstnTaxpayerMapper()

    def lookup(self, gstin: Gstin) -> GstinLookupResult | None:
        try:
            response = self._client.get(
                self._url, params={GSTIN_PARAMETER: gstin.value}, headers=self._headers
            )
        except httpx2.TimeoutException:
            log.warning("gstin_lookup.timeout")
            return None
        except httpx2.TransportError as exc:
            log.warning("gstin_lookup.unreachable", error=type(exc).__name__)
            return None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            event = "unavailable" if response.status_code >= 500 else "refused"
            log.warning(f"gstin_lookup.{event}", status_code=response.status_code)
            return None
        try:
            payload: object = response.json()
        except ValueError:
            log.warning("gstin_lookup.malformed", reason="the body is not JSON")
            return None
        result = self._mapper.map(gstin, payload)
        if result is None:
            log.warning(
                "gstin_lookup.malformed", reason="no legal name, or the record names another GSTIN"
            )
        return result
