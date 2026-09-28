"""The Maharashtra GST department's notifications page.

``/en/notifications`` is one HTML page with several tabbed tables (serial number, subject,
file). Rows carry no date, so every row is listed whatever ``since`` says and the digest of
the PDF decides whether it is new. Subjects mix Marathi, Hindi and English; user manuals sit
in the same tables as notifications, which the detector sorts out downstream.
"""

import re
from collections.abc import Iterable
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

from domain_kernel.documents import DiscoveredDocument, DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from pipeline.infrastructure.adapters._shared import fetch_bytes
from pipeline.infrastructure.http import PoliteClient

BASE_URL = "https://mahagst.gov.in"
LISTING_PATH = "/en/notifications"
_ROW = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_CELLS = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_HREF = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


class MahagstAdapter:
    def __init__(
        self, client: PoliteClient, source_id: SourceId, *, base_url: str = BASE_URL
    ) -> None:
        self._client = client
        self._source_id = source_id
        self._base_url = base_url.rstrip("/")

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        response = self._client.get(f"{self._base_url}{LISTING_PATH}")
        response.raise_for_status()
        seen: set[str] = set()
        for url, subject in parse_rows(response.text, self._base_url):
            if url in seen:
                continue
            seen.add(url)
            yield DiscoveredDocument(
                ref=DocumentRef(self._source_id, url, external_ref=url.rsplit("/", 1)[-1]),
                title=subject,
            )

    def fetch(self, ref: DocumentRef) -> RawDocument:
        return fetch_bytes(self._client, ref, media_type="application/pdf")


def parse_rows(html: str, base_url: str) -> Iterable[tuple[str, str]]:
    """``(absolute pdf url, subject)`` per row with a PDF link; the subject loses its stars."""
    for row in _ROW.findall(html):
        cells = _CELLS.findall(row)
        link = _HREF.search(row)
        if len(cells) < 2 or link is None:
            continue
        subject = " ".join(unescape(_TAG.sub("", cells[1])).replace("*", " ").split())
        yield urljoin(base_url + "/", unescape(link.group(1)).replace(" ", "%20")), subject
