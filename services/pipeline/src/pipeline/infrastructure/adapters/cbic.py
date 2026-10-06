"""CBIC's tax information portal: Central Tax notifications and CGST circulars.

The portal is a single-page application over a JSON API. Listings need an anonymous token:
``POST /api/authenticate-token`` with an empty JSON body returns ``{"id_token": ...}``, sent
back as ``Authorization1: homeToken <token>`` together with ``language: en``. Listings are per
year and page, newest first, and a page past the end is an empty list. A document's PDF is served
as JSON, ``{"data": <base64>, "fileName": ...}``, and every notification has an English and a
Hindi PDF; the adapter lists the English one and records the Hindi path as an alternate.

One adapter reads every listing: ``listing`` picks the API path and the fields its items carry
(``LISTINGS``), and ``category`` the portal's category within it. ``RECORDED_CATEGORIES`` are
the ones read so far, each with its listing recorded under tests/fixtures/cbic; the registry
refuses any other, so a new category comes with its fixture.
"""

import base64
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from urllib.parse import quote

from domain_kernel.documents import DiscoveredDocument, DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from pipeline.infrastructure.adapters._shared import on_or_after, parse_iso_date
from pipeline.infrastructure.http import PoliteClient

BASE_URL = "https://taxinformation.cbic.gov.in"
GST_TAX_ID = "1000001"
PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class CbicListing:
    """One of the portal's listings: its API path and the fields of its items."""

    path: str
    number_field: str
    title_field: str
    date_field: str


LISTINGS: Final[Mapping[str, CbicListing]] = {
    "notifications": CbicListing(
        "/api/cbic-notification-msts/fetchNotificationByYearAndCategory",
        "notificationNo",
        "notificationName",
        "notificationDt",
    ),
    "circulars": CbicListing(
        "/api/cbic-circular-msts/fetchCircularByYearCategory",
        "circularNo",
        "circularName",
        "circularDt",
    ),
}
RECORDED_CATEGORIES: Final[Mapping[str, tuple[str, ...]]] = {
    "notifications": ("Central Tax",),
    "circulars": ("Circulars CGST",),
}
"""The categories read in each listing, each with a recorded listing under tests/fixtures/cbic."""


class CbicAdapter:
    """Lists one category of one listing, newest first, and fetches its PDFs."""

    def __init__(
        self,
        client: PoliteClient,
        source_id: SourceId,
        *,
        listing: str,
        category: str,
        base_url: str = BASE_URL,
    ) -> None:
        if listing not in LISTINGS:
            raise ValueError(f"unknown CBIC listing {listing!r}; known: {', '.join(LISTINGS)}")
        self._client = client
        self._source_id = source_id
        self._listing = LISTINGS[listing]
        self._category = category
        self._base_url = base_url.rstrip("/")
        self._token: str | None = None

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        for year in range(datetime.now(since.tzinfo).year, since.year - 1, -1):
            for item in self._pages(year):
                published = parse_iso_date(item.get(self._listing.date_field))
                if not on_or_after(published, since):
                    return
                yield self._discovered(item, published)

    def fetch(self, ref: DocumentRef) -> RawDocument:
        response = self._client.get(ref.url, headers=self._headers())
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        content = response.content
        if "json" in content_type or content.startswith(b"{"):
            wrapper = json.loads(content)
            content = base64.b64decode(wrapper["data"])
        return RawDocument.from_bytes(ref, content, "application/pdf")

    def _pages(self, year: int) -> Iterator[Mapping[str, Any]]:
        page = 0
        while True:
            url = (
                f"{self._base_url}{self._listing.path}?year={year}&page={page}&size={PAGE_SIZE}"
                f"&taxId={GST_TAX_ID}&category={quote(self._category)}"
            )
            response = self._client.get(url, headers=self._headers())
            if response.status_code == 401:
                self._token = None
                response = self._client.get(url, headers=self._headers())
            response.raise_for_status()
            items = response.json()
            if not isinstance(items, list) or not items:
                return
            yield from (item for item in items if isinstance(item, Mapping))
            page += 1

    def _discovered(self, item: Mapping[str, Any], published: Any) -> DiscoveredDocument:
        path = str(item.get("docFilePath", "")).replace("\\", "/")
        return DiscoveredDocument(
            ref=DocumentRef(
                self._source_id,
                f"{self._base_url}/content/pdf/{path}",
                external_ref=str(item.get(self._listing.number_field, "")),
            ),
            title=str(item.get(self._listing.title_field, "")).strip(),
            published_at=published,
        )

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            response = self._client.post_json(f"{self._base_url}/api/authenticate-token", {})
            response.raise_for_status()
            self._token = str(response.json()["id_token"])
        return {"Authorization1": f"homeToken {self._token}", "language": "en"}


def hindi_alternate(item: Mapping[str, Any], *, base_url: str = BASE_URL) -> str | None:
    """The URL of the Hindi PDF of a listing item, when the listing names one."""
    path = str(item.get("docFilePath", "")).replace("\\", "/")
    hindi = str(item.get("docFileNameHi", "") or "")
    if not path or not hindi:
        return None
    directory = path.rsplit("/", 1)[0]
    return f"{base_url.rstrip('/')}/content/pdf/{directory}/{hindi}"
