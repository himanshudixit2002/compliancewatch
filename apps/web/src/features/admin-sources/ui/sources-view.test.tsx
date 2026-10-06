import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { sourceFromDto } from "@/entities/pipeline/mappers";
import { crawlRunDto, sourceDto, uploadSourceDto } from "@/test/pipeline-fixture";
import { addSourceNote, runSummary, sourcesView, type CrawlState } from "../model/sources";
import { SourcesError, SourcesView } from "./sources-view";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.sources", href: "/admin/sources", label: "Sources" },
];

const FLAG = {
  name: "pipeline.crawl",
  variable: "CW_PIPELINE_CRAWL_ENABLED",
  defaultOn: false,
  owner: "regulatory-intelligence",
};

function view(crawl: CrawlState["latestScheduled"]) {
  return sourcesView(
    [
      sourceFromDto(sourceDto({ last_error: "Example listing error" })),
      sourceFromDto(
        sourceDto({
          key: "example_backfilled",
          name: "Example backfilled",
          status: "failing",
          freshness: {
            state: "stale",
            age_seconds: 99_999,
            cadence_seconds: 7200,
            cadences: 13.89,
          },
          latest_run: crawlRunDto({ trigger: "backfill", status: "failed" }),
        }),
      ),
      sourceFromDto(uploadSourceDto()),
    ],
    { flag: FLAG, latestScheduled: crawl },
  );
}

describe("SourcesView", () => {
  it("lists each source with its state, freshness, latest crawl and watermark, under the crawl switch", async () => {
    const { container } = render(
      <SourcesView title="Sources" crumbs={CRUMBS} view={view({ kind: "none" })} addNote={null} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Sources" })).toBeDefined();
    const banner = container.querySelector("[data-slot='crawl-banner']");
    expect(banner?.textContent).toContain("Crawling (pipeline.crawl)");
    expect(banner?.textContent).toContain("Crawling is off by default");
    expect(banner?.textContent).toContain("CW_PIPELINE_CRAWL_ENABLED");
    expect(banner?.textContent).toContain("The schedule has not crawled any source.");
    expect(screen.getByRole("table", { name: "Sources by key: 3" })).toBeDefined();
    const first = container.querySelector("[data-source='example_notices']");
    expect(first?.textContent).toContain("Example listing error");
    expect(first?.textContent).toContain("Every 2 h");
    expect(first?.textContent).toContain("1 Jan 2000");
    expect(screen.getByRole("link", { name: "Example notices" }).getAttribute("href")).toBe(
      "/admin/sources/example_notices",
    );
    const backfilled = container.querySelector("[data-source='example_backfilled']");
    expect(backfilled?.getAttribute("data-freshness")).toBe("stale");
    expect(backfilled?.textContent).toContain("Backfill");
    const upload = container.querySelector("[data-source='example_statutes']");
    expect(upload?.textContent).toContain("Uploaded, never crawled");
    expect(upload?.textContent).toContain("Upload-only");
    expect(upload?.textContent).toContain("No crawl yet");
    const counts = container.querySelector("[data-slot='source-counts']");
    expect(counts?.textContent).toContain("Failing1");
    expect(counts?.textContent).toContain("Late or stale1");
    expect(counts?.textContent).toContain("Upload-only1");
    expect(container.querySelector("[data-slot='add-source-note']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("names the schedule's latest crawl or why it could not be read, and the note for an admin", () => {
    const run = runSummary(sourceFromDto(sourceDto()).latestRun!);
    const { container, rerender } = render(
      <SourcesView
        title="Sources"
        crumbs={CRUMBS}
        view={view({ kind: "run", sourceKey: "example_notices", summary: run })}
        addNote={addSourceNote()}
      />,
    );
    expect(container.querySelector("[data-slot='latest-scheduled']")?.textContent).toContain(
      "The schedule's latest crawl: example_notices, Completed, started",
    );
    expect(container.querySelector("[data-slot='add-source-note']")?.textContent).toContain(
      "POST /v1/pipeline/sources",
    );
    rerender(
      <SourcesView
        title="Sources"
        crumbs={CRUMBS}
        view={view({ kind: "error", message: "Example failure", correlationId: "req-1" })}
        addNote={null}
      />,
    );
    expect(container.querySelector("[data-slot='latest-scheduled']")?.textContent).toContain(
      "could not be read: Example failure (correlation id req-1)",
    );
  });

  it("says why the list is empty, and shows a failed read with its correlation id", async () => {
    const empty = sourcesView([], {
      flag: { ...FLAG, defaultOn: true },
      latestScheduled: { kind: "none" },
    });
    const { container, rerender } = render(
      <SourcesView title="Sources" crumbs={CRUMBS} view={empty} addNote={null} />,
    );
    expect(screen.getByRole("heading", { name: "The pipeline lists no source" })).toBeDefined();
    expect(container.textContent).toContain("declares crawling on by default");
    rerender(
      <SourcesError
        title="Sources"
        crumbs={CRUMBS}
        error={{
          message: "Example outage",
          status: 503,
          requestId: "req-2",
          problem: { detail: "Example detail" },
        }}
      />,
    );
    expect(screen.getByText("Example outage")).toBeDefined();
    expect(screen.getByText("req-2")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
