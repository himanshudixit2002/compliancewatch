"""CBIC's tax information portal: Central Tax notifications and CGST circulars.

The portal is a single-page application over a JSON API. Listings need an anonymous token:
``POST /api/authenticate-token`` with an empty JSON body returns ``{"id_token": ...}``, sent
back as ``Authorization1: homeToken <token>`` together with ``language: en``. Listings are per
year and page, newest first, and a page past the end is an empty list. A document's PDF is served
as JSON, ``{"data": <base64>, "fileName": ...}``, and every notification has an English and a
Hindi PDF; the adapter lists the English one and records the Hindi path as an alternate.
"""

import base64
import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

from domain_kernel.documents import DiscoveredDocument, DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from pipeline.infrastructure.adapters._shared import on_or_after, parse_iso_date
from pipeline.infrastructure.http import PoliteClient

BASE_URL = "https://taxinformation.cbic.gov.in"
GST_TAX_ID = "1000001"
PAGE_SIZE = 10


class CbicAdapter:
    """Shared listing and fetch logic; the two subclasses differ only in endpoint and fields."""

    listing_path: str
    category: str
    number_field: str
    title_field: str
    date_field: str

    def __init__(
        self, client: PoliteClient, source_id: SourceId, *, base_url: str = BASE_URL
    ) -> None:
        self._client = client
        self._source_id = source_id
        self._base_url = base_url.rstrip("/")
        self._token: str | None = None

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        for year in range(datetime.now(since.tzinfo).year, since.year - 1, -1):
            for item in self._pages(year):
                published = parse_iso_date(item.get(self.date_field))
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
                f"{self._base_url}{self.listing_path}?year={year}&page={page}&size={PAGE_SIZE}"
                f"&taxId={GST_TAX_ID}&category={quote(self.category)}"
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
                external_ref=str(item.get(self.number_field, "")),
            ),
            title=str(item.get(self.title_field, "")).strip(),
            published_at=published,
        )

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            response = self._client.post_json(f"{self._base_url}/api/authenticate-token", {})
            response.raise_for_status()
            self._token = str(response.json()["id_token"])
        return {"Authorization1": f"homeToken {self._token}", "language": "en"}


class CbicNotificationsAdapter(CbicAdapter):
    listing_path = "/api/cbic-notification-msts/fetchNotificationByYearAndCategory"
    category = "Central Tax"
    number_field = "notificationNo"
    title_field = "notificationName"
    date_field = "notificationDt"


class CbicCircularsAdapter(CbicAdapter):
    listing_path = "/api/cbic-circular-msts/fetchCircularByYearCategory"
    category = "Circulars CGST"
    number_field = "circularNo"
    title_field = "circularName"
    date_field = "circularDt"


def hindi_alternate(item: Mapping[str, Any], *, base_url: str = BASE_URL) -> str | None:
    """The URL of the Hindi PDF of a listing item, when the listing names one."""
    path = str(item.get("docFilePath", "")).replace("\\", "/")
    hindi = str(item.get("docFileNameHi", "") or "")
    if not path or not hindi:
        return None
    directory = path.rsplit("/", 1)[0]
    return f"{base_url.rstrip('/')}/content/pdf/{directory}/{hindi}"
