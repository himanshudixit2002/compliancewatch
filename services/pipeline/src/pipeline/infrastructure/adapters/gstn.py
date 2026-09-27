"""GSTN's News and Updates: the advisories the portal publishes.

The page is built from ``/fomessage/newsupdates``, a JSON feed ``{"data": [...]}`` with one
item per advisory: ``id``, ``title``, ``module``, ``content`` (HTML), ``date`` (``dd/mm/yyyy``),
``IsExternal`` and ``linkURl``. The feed is the document: each advisory is fetched as the HTML
of its own item, so a re-fetch of an unchanged advisory keeps its digest.
"""

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from domain_kernel.documents import DiscoveredDocument, DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from pipeline.infrastructure.adapters._shared import on_or_after, parse_dmy
from pipeline.infrastructure.http import PoliteClient

BASE_URL = "https://www.gst.gov.in"
FEED_PATH = "/fomessage/newsupdates"
ITEM_URL = "https://www.gst.gov.in/newsandupdates/read/{id}"


class GstnAdapter:
    def __init__(
        self, client: PoliteClient, source_id: SourceId, *, base_url: str = BASE_URL
    ) -> None:
        self._client = client
        self._source_id = source_id
        self._base_url = base_url.rstrip("/")
        self._items: dict[str, Mapping[str, Any]] = {}

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        for item in self._feed():
            published = parse_dmy(str(item.get("date", "")))
            if not on_or_after(published, since):
                continue
            yield DiscoveredDocument(
                ref=DocumentRef(
                    self._source_id, self._item_url(item), external_ref=str(item["id"])
                ),
                title=str(item.get("title", "")).strip(),
                published_at=published,
            )

    def fetch(self, ref: DocumentRef) -> RawDocument:
        item = self._items.get(ref.external_ref)
        if item is None:
            item = next((i for i in self._feed() if str(i.get("id")) == ref.external_ref), None)
        if item is None:
            raise LookupError(f"advisory {ref.external_ref} is no longer in the feed")
        title, module = item.get("title", ""), item.get("module", "")
        html = (
            f"<html><head><title>{title}</title></head><body>"
            f"<h1>{title}</h1><p>{item.get('date', '')} | {module}</p>"
            f"{item.get('content', '')}</body></html>"
        )
        return RawDocument.from_bytes(ref, html.encode("utf-8"), "text/html")

    def _feed(self) -> list[Mapping[str, Any]]:
        response = self._client.get(
            f"{self._base_url}{FEED_PATH}", headers={"accept": "application/json"}
        )
        response.raise_for_status()
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise LookupError(
                "the advisories feed answered with something other than JSON"
            ) from exc
        items = [
            item for item in body.get("data", []) if isinstance(item, Mapping) and "id" in item
        ]
        self._items = {str(item["id"]): item for item in items}
        return items

    def _item_url(self, item: Mapping[str, Any]) -> str:
        if str(item.get("IsExternal", "N")).upper() == "Y" and item.get("linkURl"):
            return str(item["linkURl"])
        return ITEM_URL.format(id=item["id"])
