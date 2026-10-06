"""The source manager and a crawl through the one deployable, over recorded notifications.

The whole app runs as ``cw-mvp serve`` runs it, on memory stores, with crawling on and the
pipeline's crawl starter, adapter types and store handed in: a recording starter (no Temporal),
the registry's types plus the test type ``recorded``, whose adapter lists recorded Central Tax
notifications and fetches their recorded PDFs (no network). An admin adds a source of that type
on the internal listener with the shared write token and starts a crawl, which answers 202 with
its run at once. The crawl then runs as the worker runs it, step by step: the listing from the
watermark, the child ingest's fetch-and-store and parse of each new notification, and the
bookkeeping. The source reads healthy and fresh with its documents, which come a page at a time
with their stored bytes. A second crawl skips the URLs it has, the tick starts each source once
per cadence slot, and the public listener answers none of these admin routes in header mode.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, Final
from uuid import UUID

import httpx2

from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from pipeline.application.activities import FetchAndStore, ParseDocument, ParseRequest
from pipeline.application.crawl import (
    ChildOutcome,
    FinishCrawl,
    FinishRequest,
    ListNewDocuments,
    ListRequest,
    ScheduleCrawls,
)
from pipeline.application.store_document import StoreDocument
from pipeline.domain.crawl import Outcome
from pipeline.domain.sources import watermark_of
from pipeline.infrastructure.adapters import RegistryAdapterTypes, StoreCatalog
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.testing import MemoryCrawls, recorded_client, recorded_types

BASE: Final = "/v1/pipeline"
TOKEN: Final = "journey-write-token"
WRITE: Final = {"x-cw-write-token": TOKEN}
ACTOR: Final = str(UUID(int=42))
ROUTE_NOT_FOUND: Final = "urn:compliancewatch:problem:route-not-found"
NUMBERS: Final = ["01/2026-Central Tax", "17/2025-Central Tax", "15/2025-Central Tax"]
TODAY: Final = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)


class Pipeline:
    """The pipeline's store, raw store and crawl starter, shared by the app and the steps the
    worker would run."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.starter = MemoryCrawls()
        self.catalog = StoreCatalog(self.store, recorded_client(), types=recorded_types())

    def overrides(self) -> dict[str, dict[str, Any]]:
        return {
            "pipeline": {
                "units": self.store,
                "raw_store": self.raw,
                "starter": self.starter,
                "adapter_types": RegistryAdapterTypes(recorded_types()),
            }
        }

    async def crawl(self, run_id: str) -> None:
        """What the crawl workflow does with the run, one step after another."""
        listing = await ListNewDocuments(self.store, self.catalog, clock=lambda: TODAY).run(
            ListRequest(source_key="recorded_cbic", run_id=UUID(run_id))
        )
        fetch = FetchAndStore(StoreDocument(self.catalog, self.store, self.raw))
        parse = ParseDocument(ParserChain(self.catalog), self.raw)
        outcomes = []
        for document in listing.new:
            stored = await fetch.run(document)
            parsed = await parse.run(ParseRequest(document_id=stored.document_id, stored=stored))
            assert parsed.clause_count > 3
            kind = Outcome.DUPLICATE if stored.duplicate else Outcome.STORED
            outcomes.append(
                ChildOutcome(url=document.url, published_at=document.published_at, outcome=kind)
            )
        await FinishCrawl(self.store).run(
            FinishRequest(
                source_key="recorded_cbic",
                run_id=UUID(run_id),
                listed=listing.listed,
                known_newest=listing.known_newest,
                deferred_oldest=listing.deferred_oldest,
                outcomes=outcomes,
            )
        )


@contextmanager
def listeners(app: CombinedApp) -> Iterator[tuple[httpx2.Client, httpx2.Client]]:
    public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
    with (
        httpx2.Client(base_url=public_url, timeout=30.0) as public,
        httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
    ):
        yield public, internal


def ok(response: httpx2.Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


def source(internal: httpx2.Client, key: str) -> dict[str, Any]:
    items = ok(internal.get(f"{BASE}/sources"))["items"]
    (found,) = [item for item in items if item["key"] == key]
    found_source: dict[str, Any] = found
    return found_source


def test_an_admin_adds_a_source_and_its_crawl_stores_the_recorded_notifications() -> None:
    pipeline = Pipeline()
    services = {
        **MEMORY_SERVICES,
        "pipeline": {
            **MEMORY_SERVICES["pipeline"],
            "pipeline_crawl_enabled": True,
            "rulebook_write_token": TOKEN,
        },
    }
    with (
        running_app(service_overrides=services, build_overrides=pipeline.overrides()) as app,
        listeners(app) as (public, internal),
    ):
        built_in = [item["key"] for item in ok(internal.get(f"{BASE}/sources"))["items"]]
        assert built_in == [
            "cbic_circulars",
            "cbic_notifications",
            "cgst_act",
            "cgst_rules",
            "gstcouncil_press",
            "gstn_advisories",
            "igst_act",
            "mahagst_notifications",
        ]
        added = ok(
            internal.post(
                f"{BASE}/sources",
                headers=WRITE,
                json={
                    "actor_id": ACTOR,
                    "reason": "Recorded notifications for the journey",
                    "key": "recorded_cbic",
                    "name": "Recorded CBIC notifications",
                    "adapter_type": "recorded",
                    "parameters": {"numbers": NUMBERS},
                    "cadence_seconds": 7200,
                },
            ),
            201,
        )
        assert (added["status"], added["regulator"], added["freshness"]["state"]) == (
            "healthy",
            "CBIC",
            "never",
        )
        edited = ok(
            internal.patch(
                f"{BASE}/sources/recorded_cbic",
                headers=WRITE,
                json={"actor_id": ACTOR, "reason": "Crawl it every hour", "cadence_seconds": 3600},
            )
        )
        assert edited["cadence_seconds"] == 3600
        # The recorded notifications date from 2025 and 2026: the source starts from the
        # watermark a backfill to 20 September 2025 would leave, so the crawl lists all three.
        with pipeline.store() as unit:
            row = unit.sources.get("recorded_cbic")
            assert row is not None
            unit.sources.save(replace(row, watermark=watermark_of(date(2025, 9, 20))))

        started = ok(
            internal.post(
                f"{BASE}/sources/recorded_cbic/fetch",
                headers=WRITE,
                json={"actor_id": ACTOR, "reason": "See the recorded notifications arrive"},
            ),
            202,
        )
        (start,) = pipeline.starter.started
        assert started["run_id"] == str(start.run_id)
        assert source(internal, "recorded_cbic")["status"] == "fetching"

        asyncio.run(pipeline.crawl(started["run_id"]))

        crawled = source(internal, "recorded_cbic")
        assert (crawled["status"], crawled["document_count"], crawled["watermark"]) == (
            "healthy",
            3,
            "2026-04-21",
        )
        assert crawled["freshness"]["state"] == "fresh"
        run = crawled["latest_run"]
        assert (run["status"], run["listed"], run["stored"], run["failed"]) == (
            "completed",
            3,
            3,
            0,
        )
        first = ok(internal.get(f"{BASE}/sources/recorded_cbic/documents", params={"limit": 2}))
        rest = ok(
            internal.get(
                f"{BASE}/sources/recorded_cbic/documents",
                params={"limit": 2, "cursor": first["next_cursor"]},
            )
        )
        refs = [item["external_ref"] for item in first["items"] + rest["items"]]
        assert refs == NUMBERS, "newest publication first"
        assert rest["next_cursor"] is None
        document = first["items"][0]
        assert ok(internal.get(f"{BASE}/documents/{document['document_id']}")) == document
        raw = internal.get(document["raw_path"])
        assert raw.status_code == 200
        assert raw.headers["content-type"] == "application/pdf"
        assert raw.content.startswith(b"%PDF")
        assert raw.headers["etag"] == f'"{document["sha256"]}"'
        assert [entry.action for entry in pipeline.store.audit] == [
            "pipeline.source.add",
            "pipeline.source.edit",
            "pipeline.source.fetch",
        ]

        again = ok(
            internal.post(
                f"{BASE}/sources/recorded_cbic/fetch",
                headers=WRITE,
                json={"actor_id": ACTOR, "reason": "Nothing new should come of this"},
            ),
            202,
        )
        asyncio.run(pipeline.crawl(again["run_id"]))
        second = source(internal, "recorded_cbic")["latest_run"]
        assert (second["listed"], second["stored"], second["duplicates"]) == (1, 0, 0)
        assert len(pipeline.store.documents) == 3

        tick = ScheduleCrawls(
            pipeline.store,
            pipeline.starter,
            types=RegistryAdapterTypes(recorded_types()),
            enabled=True,
        )
        scheduled = tick.run().started
        assert len(scheduled) == 5, (
            "the built-in sources but the upload-only statutes; the recorded one was just crawled"
        )
        refused = internal.post(
            f"{BASE}/sources/cgst_rules/fetch",
            headers=WRITE,
            json={"actor_id": ACTOR, "reason": "An upload-only source lists nothing"},
        )
        assert (refused.status_code, refused.json()["type"]) == (
            409,
            "urn:compliancewatch:problem:pipeline-source-upload-only",
        )
        assert tick.run().started == (), "a second tick starts nothing twice"

        for method, path in (
            ("GET", f"{BASE}/sources"),
            ("POST", f"{BASE}/sources/recorded_cbic/fetch"),
            ("GET", document["raw_path"]),
        ):
            refused = public.request(method, path, headers=WRITE)
            assert (refused.status_code, refused.json()["type"]) == (404, ROUTE_NOT_FOUND)
