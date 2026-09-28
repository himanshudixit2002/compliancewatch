# Recorded source fixtures

Responses recorded from the public regulator sites on 2026-09-28 with the crawler's own user
agent (a browser user agent where the site refuses others), so adapter tests never touch the
network. Each adapter's conformance test replays these files through a fake transport.

| Directory | Source | What is recorded |
| --- | --- | --- |
| `cbic/` | taxinformation.cbic.gov.in | Central Tax notification listings (`notifications-2026-p0.json`, `notifications-2025-p0.json`, `-p1.json`), CGST circular listing (`circulars-2026-p0.json`), and the JSON wrapper the site returns for a PDF (`gst-ct-01-2026.pdf.json` English, `gst-ct-01h-2026.pdf.json` Hindi: `{"data": base64, "fileName"}`). The listing API wants an anonymous token from `POST /api/authenticate-token` sent as `Authorization1: homeToken <jwt>` plus a `language` header. |
| `gstcouncil/` | gstcouncil.gov.in | The press-release archive, pages 0 and 1 (`archive-press-release-page0.html`, `-page1.html`), and one linked PDF. The live `/press-release` page lists nothing; the archive is the listing. |
| `gstn/` | gst.gov.in | `newsupdates.json`: the advisories feed behind the News and Updates page, cut to five items with shortened `content`. The site answers a plain client with an HTML gate; the browser gets JSON. |
| `mahagst/` | mahagst.gov.in | `notifications.html`: the Maharashtra GST department's notifications page (a mixed listing of PDFs). No linked PDF is recorded: every one on the page is larger than 300 KB, so the fetch test serves the GST Council PDF at a Maharashtra URL. |

Page tokens in the recorded HTML are replaced with `redacted-page-token` so the secret scanner stays quiet.
The adapter tests wire these files up in `pipeline.testing.recorded_sources`; a request the
fixtures do not cover gets a 404 with the word "unrecorded" so the failure is obvious.
Re-recording is by hand for now (the URLs are in each adapter module); a `--record` flag on
`pipeline-backfill` is on the list.
