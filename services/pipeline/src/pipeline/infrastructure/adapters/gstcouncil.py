"""The GST Council's press releases.

The live press-release page lists nothing; the archive at ``/archive-press-release?page=N`` is
a table of serial number, upload date (``dd-mm-yyyy``) and a description linking to a PDF on the
council's site or to a Press Information Bureau page. Pages count from 0 and run newest first.
"""

import re
from collections.abc import Iterable
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

from domain_kernel.documents import DiscoveredDocument, DocumentRef, RawDocument
from domain_kernel.ids import SourceId
from pipeline.infrastructure.adapters._shared import fetch_bytes, on_or_after, parse_dmy
from pipeline.infrastructure.http import PoliteClient

BASE_URL = "https://gstcouncil.gov.in"
_ROW = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_DATE_CELL = re.compile(r'views-field-field-date-of-uploading">\s*([^<]*?)\s*</td>')
_LINK = re.compile(r'views-field-title">\s*<a href="([^"]+)">(.*?)</a>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_NEXT_PAGE = re.compile(r'href="\?page=(\d+)"')


class GstCouncilAdapter:
    def __init__(
        self, client: PoliteClient, source_id: SourceId, *, base_url: str = BASE_URL
    ) -> None:
        self._client = client
        self._source_id = source_id
        self._base_url = base_url.rstrip("/")

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        page = 0
        while True:
            response = self._client.get(f"{self._base_url}/archive-press-release?page={page}")
            response.raise_for_status()
            rows = list(parse_rows(response.text, self._base_url))
            if not rows:
                return
            for date_text, url, title in rows:
                published = parse_dmy(date_text)
                if not on_or_after(published, since):
                    return
                yield DiscoveredDocument(
                    ref=DocumentRef(self._source_id, url, external_ref=url.rsplit("/", 1)[-1]),
                    title=title,
                    published_at=published,
                )
            pages = {int(number) for number in _NEXT_PAGE.findall(response.text)}
            if page + 1 not in pages:
                return
            page += 1

    def fetch(self, ref: DocumentRef) -> RawDocument:
        return fetch_bytes(self._client, ref)


def parse_rows(html: str, base_url: str) -> Iterable[tuple[str, str, str]]:
    """``(date text, absolute url, title)`` per table row that links somewhere."""
    for row in _ROW.findall(html):
        date_match = _DATE_CELL.search(row)
        link = _LINK.search(row)
        if date_match is None or link is None:
            continue
        title = " ".join(unescape(_TAG.sub("", link.group(2))).split())
        yield date_match.group(1).strip(), urljoin(base_url + "/", unescape(link.group(1))), title
