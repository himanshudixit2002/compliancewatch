import { describe, expect, it } from "vitest";
import { outboxEventFromDto, pipelineDocumentFromDto } from "@/entities/pipeline/mappers";
import {
  ACTOR_ID,
  DOCUMENT_ID,
  classificationDto,
  extractionDto,
  outboxEventDto,
  pipelineDocumentDto,
} from "@/test/pipeline-fixture";
import {
  classificationView,
  classifierLabel,
  documentRow,
  eventRow,
  extractionView,
  isFiltered,
  pagedRows,
  pipelineHref,
  readPipelineQuery,
  viewChips,
} from "./operations";

describe("readPipelineQuery and pipelineHref", () => {
  it("reads the runs view by default, with its filters and cursor", () => {
    const read = readPipelineQuery({
      source: "example_notices",
      status: "failed",
      trigger: "backfill",
      cursor: "c1",
    });
    expect(read).toEqual({
      current: {
        view: "runs",
        filter: { source: "example_notices", status: "failed", trigger: "backfill", cursor: "c1" },
      },
      invalid: {},
    });
    expect(pipelineHref(read.current)).toBe(
      "/admin/pipeline?source=example_notices&status=failed&trigger=backfill",
    );
    expect(pipelineHref(read.current, "c2")).toBe(
      "/admin/pipeline?source=example_notices&status=failed&trigger=backfill&cursor=c2",
    );
    expect(
      readPipelineQuery({ view: "runs", status: "nope", trigger: ["manual"] }).current,
    ).toEqual({
      view: "runs",
      filter: { source: null, status: null, trigger: "manual", cursor: null },
    });
  });

  it("reads the documents view and refuses a source, dates out of shape or out of order", () => {
    const read = readPipelineQuery({
      view: "documents",
      status: "triage",
      source: "example_notices",
      type: "circular",
      from: "2000-01-01",
      to: "2000-12-31",
    });
    expect(read.current).toEqual({
      view: "documents",
      filter: {
        status: "triage",
        source: "example_notices",
        type: "circular",
        from: "2000-01-01",
        to: "2000-12-31",
        cursor: null,
      },
    });
    expect(pipelineHref(read.current)).toBe(
      "/admin/pipeline?view=documents&status=triage&source=example_notices&type=circular&from=2000-01-01&to=2000-12-31",
    );
    expect(
      readPipelineQuery({ view: "documents", source: "Bad Key", from: "2000-02-30", to: "x" })
        .invalid,
    ).toEqual({ source: "Bad Key", from: "2000-02-30", to: "x" });
    expect(
      readPipelineQuery({ view: "documents", from: "2000-02-01", to: "2000-01-01" }).invalid,
    ).toEqual({
      to: "2000-01-01",
    });
  });

  it("reads the outbox view and refuses a topic out of shape", () => {
    const read = readPipelineQuery({
      view: "outbox",
      topic: "document.parsed",
      cursor: "x".repeat(600),
    });
    expect(read.current).toEqual({
      view: "outbox",
      filter: { topic: "document.parsed", cursor: null },
    });
    expect(pipelineHref(read.current)).toBe("/admin/pipeline?view=outbox&topic=document.parsed");
    expect(readPipelineQuery({ view: "outbox", topic: "Bad Topic" }).invalid).toEqual({
      topic: "Bad Topic",
    });
    expect(isFiltered(read.current)).toBe(true);
    expect(isFiltered(readPipelineQuery({ view: "outbox", cursor: "c" }).current)).toBe(false);
  });

  it("offers one chip per view, the current one marked", () => {
    expect(viewChips("documents").map((chip) => [chip.key, chip.href, chip.current])).toEqual([
      ["runs", "/admin/pipeline", false],
      ["documents", "/admin/pipeline?view=documents", true],
      ["outbox", "/admin/pipeline?view=outbox", false],
    ]);
  });
});

describe("the documents' words", () => {
  it("names the classifier, who decided, and the extraction", () => {
    expect(classifierLabel("detector@1")).toBe("The detector (detector@1)");
    expect(classifierLabel("triage")).toBe("A person's triage");
    expect(classifierLabel("retry")).toBe("A person's type, given on a retry");
    expect(classifierLabel("example@2")).toBe("example@2");
    const mine = classificationView(
      pipelineDocumentFromDto(
        pipelineDocumentDto({
          classification: classificationDto({ classifier: "triage", decided_by: ACTOR_ID }),
        }),
      ).classification!,
      ACTOR_ID,
    );
    expect(mine).toMatchObject({
      by: "A person's triage",
      decidedBy: "you",
      relevance: "Relevant",
    });
    const theirs = classificationView(
      pipelineDocumentFromDto(
        pipelineDocumentDto({
          classification: classificationDto({
            decided_by: ACTOR_ID,
            confidence: "conflict",
            route: "triage",
            relevance: "irrelevant",
          }),
        }),
      ).classification!,
      null,
    );
    expect(theirs).toMatchObject({
      decidedBy: ACTOR_ID,
      relevance: "Not a regulatory document",
      confidence: "Conflict: the text names another type than the source publishes",
      route: "Held for a person's triage",
    });
    expect(
      extractionView(
        pipelineDocumentFromDto(
          pipelineDocumentDto({ extraction: extractionDto({ outcome: "unparseable" }) }),
        ).extraction!,
      ).outcome,
    ).toBe("No candidate: the model gave none, twice");
  });

  it("words a document row with its links", () => {
    const row = documentRow(pipelineDocumentFromDto(pipelineDocumentDto()), null);
    expect(row).toMatchObject({
      documentId: DOCUMENT_ID,
      href: `/admin/pipeline/documents/${DOCUMENT_ID}`,
      sourceHref: "/admin/sources/example_notices",
      readAs: "Notification",
      published: "1 Jan 2000",
      classification: { by: "The detector (detector@1)", decidedBy: null },
      extraction: { outcome: "A rule candidate", issues: "Issues raised: 1", needsReview: true },
    });
    const bare = documentRow(
      pipelineDocumentFromDto(
        pipelineDocumentDto({
          title: "",
          external_ref: "",
          published_on: null,
          classification: null,
          extraction: null,
        }),
      ),
      null,
    );
    expect(bare).toMatchObject({
      title: "Untitled document",
      published: null,
      classification: null,
      extraction: null,
    });
  });

  it("words a dead row's summary and pages a list", () => {
    const row = eventRow(
      outboxEventFromDto(
        outboxEventDto({
          summary: { document_id: DOCUMENT_ID, count: 2, flag: true, none: null, list: [1] },
        }),
      ),
    );
    expect(row.summary).toEqual([
      ["document_id", DOCUMENT_ID],
      ["count", "2"],
      ["flag", "true"],
      ["none", "None"],
      ["list", "[1]"],
    ]);
    expect(row.deadAt).toBe("1 Jan 2000, 10:30 am IST");
    expect(eventRow(outboxEventFromDto(outboxEventDto({ dead_at: null }))).deadAt).toBeNull();
    const current = readPipelineQuery({ view: "outbox", cursor: "c1" }).current;
    const paged = pagedRows(current, { items: [1, 2], nextCursor: "c2" }, (value) => value * 2);
    expect(paged).toEqual({
      rows: [2, 4],
      nextHref: "/admin/pipeline?view=outbox&cursor=c2",
      firstHref: "/admin/pipeline?view=outbox",
      later: true,
    });
  });
});
