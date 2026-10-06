import { describe, expect, it } from "vitest";
import { sourceFromDto } from "@/entities/pipeline/mappers";
import { SOURCE_STATUSES, FRESHNESS_STATES } from "@/entities/pipeline/types";
import { crawlRunDto, sourceDto, uploadSourceDto } from "@/test/pipeline-fixture";
import {
  addSourceNote,
  cadenceText,
  formatCount,
  formatSeconds,
  freshnessLabel,
  freshnessText,
  freshnessTone,
  runSummary,
  sourceCounts,
  sourceRow,
  sourceStatusLabel,
  sourceStatusTone,
  sourcesView,
  switchesShort,
  switchesText,
} from "./sources";

const CRAWL = {
  flag: {
    name: "pipeline.crawl",
    variable: "CW_PIPELINE_CRAWL_ENABLED",
    defaultOn: false,
    owner: "x",
  },
  latestScheduled: { kind: "none" } as const,
};

describe("the source registry's words", () => {
  it("names every status and freshness the pipeline sends, and humanises a new one", () => {
    for (const status of SOURCE_STATUSES) {
      expect(sourceStatusLabel(status), status).not.toBe(status);
    }
    for (const state of FRESHNESS_STATES) expect(freshnessLabel(state), state).not.toBe(state);
    expect(sourceStatusLabel("example_new")).toBe("Example new");
    expect(sourceStatusTone("failing")).toBe("danger");
    expect(sourceStatusTone("example_new")).toBe("neutral");
    expect(freshnessLabel("example_new")).toBe("Example new");
    expect(freshnessTone("stale")).toBe("danger");
    expect(freshnessTone("example_new")).toBe("neutral");
  });

  it("says a length of time rounded down to its largest units", () => {
    expect(formatSeconds(45)).toBe("45 s");
    expect(formatSeconds(-3)).toBe("0 s");
    expect(formatSeconds(12 * 60 + 59)).toBe("12 min");
    expect(formatSeconds(7200)).toBe("2 h");
    expect(formatSeconds(9000)).toBe("2 h 30 min");
    expect(formatSeconds(86_400)).toBe("1 d");
    expect(formatSeconds(86_400 + 6 * 3600 + 59)).toBe("1 d 6 h");
    expect(cadenceText(7200)).toBe("Every 2 h");
    expect(formatCount(123456)).toBe("1,23,456");
  });

  it("says how fresh a source's last listing is, in time and in cadences", () => {
    expect(
      freshnessText({ state: "late", ageSeconds: 9000, cadenceSeconds: 7200, cadences: 1.25 }),
    ).toBe("Listed 2 h 30 min ago, 1.25 cadences");
    expect(
      freshnessText({ state: "fresh", ageSeconds: 60, cadenceSeconds: 7200, cadences: null }),
    ).toBe("Listed 1 min ago");
    expect(
      freshnessText({ state: "never", ageSeconds: null, cadenceSeconds: 7200, cadences: null }),
    ).toBeNull();
  });

  it("says whether the schedule may crawl a source, in a word for the list", () => {
    expect(switchesShort({ enabled: false, paused: true, listable: true })).toBe(
      "Disabled and paused",
    );
    expect(switchesShort({ enabled: true, paused: true, listable: true })).toBe("Paused");
    expect(switchesShort({ enabled: true, paused: true, listable: false })).toBe("Upload-only");
    expect(switchesText({ enabled: true, paused: false, listable: true })).toMatch(/^Enabled/);
    expect(switchesText({ enabled: false, paused: false, listable: true })).toMatch(/^Disabled:/);
    expect(switchesText({ enabled: true, paused: true, listable: true })).toMatch(/^Paused/);
    expect(switchesText({ enabled: false, paused: true, listable: true })).toMatch(
      /^Disabled and paused/,
    );
    expect(switchesText({ enabled: true, paused: false, listable: false })).toMatch(/^Upload-only/);
  });
});

describe("sourceRow and sourcesView", () => {
  it("words a listing source with its latest run and watermark", () => {
    const row = sourceRow(sourceFromDto(sourceDto({ last_error: "Example error" })));
    expect(row).toMatchObject({
      key: "example_notices",
      href: "/admin/sources/example_notices",
      docType: "Notification",
      documents: "42",
      statusLabel: "Healthy",
      statusTone: "success",
      uploadOnly: false,
      switches: "Enabled",
      cadence: "Every 2 h",
      freshness: { state: "fresh", label: "Fresh", tone: "success" },
      watermark: "1 Jan 2000",
      lastError: "Example error",
      latestRun: {
        status: "completed",
        statusLabel: "Completed",
        triggerLabel: "Schedule",
        backfill: false,
      },
    });
    expect(row.lastListed?.iso).toBe("2000-01-01T04:31:05Z");
  });

  it("words an upload-only source, which has no run, listing or watermark", () => {
    const row = sourceRow(sourceFromDto(uploadSourceDto()));
    expect(row).toMatchObject({
      uploadOnly: true,
      switches: "Upload-only",
      latestRun: null,
      lastListed: null,
      watermark: null,
      docType: "Statute",
    });
  });

  it("marks a backfill as one and counts the sources that need a look", () => {
    expect(
      runSummary(
        sourceFromDto(sourceDto({ latest_run: crawlRunDto({ trigger: "backfill" }) })).latestRun!,
      ).backfill,
    ).toBe(true);
    const sources = [
      sourceFromDto(sourceDto()),
      sourceFromDto(
        sourceDto({
          key: "example_two",
          status: "failing",
          freshness: { state: "stale", age_seconds: 99999, cadence_seconds: 7200, cadences: 13.9 },
        }),
      ),
      sourceFromDto(
        sourceDto({
          key: "example_three",
          freshness: { state: "late", age_seconds: 9000, cadence_seconds: 7200, cadences: 1.25 },
        }),
      ),
      sourceFromDto(uploadSourceDto()),
    ];
    expect(sourceCounts(sources)).toEqual({ total: 4, failing: 1, behind: 2, uploadOnly: 1 });
    const view = sourcesView(sources, CRAWL);
    expect(view.rows.map((row) => row.key)).toEqual([
      "example_notices",
      "example_two",
      "example_three",
      "example_statutes",
    ]);
    expect(view.crawl).toBe(CRAWL);
  });

  it("takes the note on adding a source from its registry entry", () => {
    const note = addSourceNote();
    expect(note.title).toBe("Add a source");
    expect(note.routes).toEqual(["POST /v1/pipeline/sources"]);
    expect(note.notes).toContain("POST /v1/pipeline/sources");
  });
});
