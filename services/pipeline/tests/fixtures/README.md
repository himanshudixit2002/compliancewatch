# Recorded source fixtures

Responses recorded from the public regulator sites on 2026-09-28 with the crawler's own user
agent (a browser user agent where the site refuses others), so adapter tests never touch the
network. Each adapter's conformance test replays these files through a fake transport.

| Directory | Source | What is recorded |
| --- | --- | --- |
| `cbic/` | taxinformation.cbic.gov.in | Central Tax notification listings (`notifications-2026-p0.json`, `notifications-2025-p0.json`, `-p1.json`), CGST circular listing (`circulars-2026-p0.json`), and the JSON wrapper the site returns for a PDF (`{"data": base64, "fileName"}`) for five Central Tax notifications in English: 01/2026 (`gst-ct-01-2026.pdf.json`, also in Hindi as `gst-ct-01h-2026.pdf.json`), 17/2025 (`gst-ct-17-2025.pdf.json`), 15/2025 (`centaltax-15-2025.pdf.json`), 10/2025 (`gst-ct-10-2025.pdf.json`) and 13/2024 (`central-tax-13-2024-11072024.pdf.json`); `pipeline.testing.RECORDED_NOTIFICATIONS` lists them. The listing API wants an anonymous token from `POST /api/authenticate-token` sent as `Authorization1: homeToken <jwt>` plus a `language` header. |
| `gstcouncil/` | gstcouncil.gov.in | The press-release archive, pages 0 and 1 (`archive-press-release-page0.html`, `-page1.html`), and one linked PDF. The live `/press-release` page lists nothing; the archive is the listing. |
| `gstn/` | gst.gov.in | `newsupdates.json`: the advisories feed behind the News and Updates page, cut to five items with shortened `content`. The site answers a plain client with an HTML gate; the browser gets JSON. |
| `mahagst/` | mahagst.gov.in | `notifications.html`: the Maharashtra GST department's notifications page (a mixed listing of PDFs). No linked PDF is recorded: every one on the page is larger than 300 KB, so the fetch test serves the GST Council PDF at a Maharashtra URL. |

Page tokens in the recorded HTML are replaced with `redacted-page-token` so the secret scanner stays quiet.
The adapter tests wire these files up in `pipeline.testing.recorded_sources`; a request the
fixtures do not cover gets a 404 with the word "unrecorded" so the failure is obvious.
The four notifications added after the first recording were fetched with
`pipeline-label prepare --index evals/golden/extraction/cbic_notifications/index.yaml --number
"<number>" --record services/pipeline/tests/fixtures/cbic`, which also writes the draft case file.
10/2025-Central Tax is the table-heavy one: it substitutes entries of a table of
Commissionerates and their districts, each entry wrapping over several lines, and the parser
chain's tests read its rows with the table-aware PDF parser. The other four are prose. The GST
Council archive pages and the Maharashtra GST page hold listing tables, which the table-aware
HTML parser's tests read.
Other sources are re-recorded by hand (the URLs are in each adapter module).

## Workflow histories

`histories/` holds runs of `pipeline.ingest_document`, recorded on 2026-10-06 on a local
Temporal dev server on the sample notification of `pipeline.infrastructure.fakes`, each pair one
run with knowledge off and one with registration, embedding and the extraction child:

- `ingest-before-store.json` and `ingest-before-store-knowledge.json`, with the code before
  `FetchAndStore`: both fetched with `pipeline.fetch_document`, whose result carries the bytes;
- `ingest-with-store.json` and `ingest-with-store-knowledge.json`, with `FetchAndStore` and before
  a crawl could hand an ingest its document (`GIVEN_PATCH`): both discovered it first;
- `ingest-with-crawl.json` and `ingest-with-crawl-knowledge.json`, handed their document as a
  crawl hands it, before a document that does not parse opened a manual-parse task; and
  `ingest-with-crawl-unparsed.json`, handed a synthetic PDF with no text layer
  (`https://example.invalid/notifications/18-2026-scanned`) and the real parsers, whose parse
  failed with `UnparsedDocumentError` and failed the ingest. Its failures' stack traces were
  emptied after recording, so no local path is committed; replay never reads them.
- `ingest-with-parse*.json`, recorded on 2026-10-06 with the parser chain, uploads and manual
  parse, before the classify step and rule extraction: `ingest-with-parse.json` and
  `-knowledge.json`, handed the sample notification as a crawl hands it, with knowledge off and on;
  `-upload.json`, an upload's stored document (`STORED_PATCH`) with knowledge on;
  `-statute.json`, an analyst's transcript of a stored statute, registered and embedded and never
  extracted; and `-unparsed.json`, handed a synthetic PDF with no text layer
  (`https://example.invalid/notifications/18-2026-scanned`) and the real parsers, whose parse
  failure opened its manual-parse task (`PARSE_PATCH`). Stack traces emptied the same way.

The worker's identity in them reads `1@pipeline-history`. `tests/unit/test_workflow_replay.py`
replays them on today's workflow; record a new pair (`WorkflowHandle.fetch_history()`,
`WorkflowHistory.to_json()`) before the next change that a patch guards.
