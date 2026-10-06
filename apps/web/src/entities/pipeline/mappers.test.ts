import { describe, expect, it } from "vitest";
import {
  ACTOR_ID,
  DOCUMENT_ID,
  EVENT_ID,
  RUN_ID,
  SOURCE_KEY,
  TASK_ID,
  classificationDto,
  crawlRunDto,
  documentDetailDto,
  documentDto,
  outboxEventDto,
  pipelineDocumentDto,
  retryDto,
  runDto,
  sourceDto,
  taskDto,
  triageTaskDto,
  uploadSourceDto,
} from "@/test/pipeline-fixture";
import {
  crawlRunFromDto,
  documentDetailFromDto,
  fetchStartedFromDto,
  outboxEventFromDto,
  pageFromDto,
  pipelineDocumentFromDto,
  requeuedFromDto,
  retryAcceptedFromDto,
  sourceEditToDto,
  sourceFromDto,
  storedDocumentFromDto,
  taskFromDto,
  taskResolvedFromDto,
  transcriptToDto,
  triageToDto,
  uploadStoredFromDto,
} from "./mappers";

describe("pipeline mappers", () => {
  it("maps a source with its freshness and latest run", () => {
    const source = sourceFromDto(sourceDto());
    expect(source).toMatchObject({
      key: SOURCE_KEY,
      name: "Example notices",
      adapterType: "example",
      regulator: "EXAMPLE",
      docType: "notification",
      cadenceSeconds: 7200,
      listable: true,
      status: "healthy",
      documentCount: 42,
      watermark: "2000-01-01",
      freshness: { state: "fresh", ageSeconds: 1800, cadenceSeconds: 7200, cadences: 0.25 },
    });
    expect(source.latestRun).toMatchObject({ runId: RUN_ID, sourceKey: null, trigger: "schedule" });
    const upload = sourceFromDto(uploadSourceDto());
    expect(upload).toMatchObject({
      listable: false,
      site: null,
      lastFetchAt: null,
      latestRun: null,
      freshness: { state: "never", ageSeconds: null, cadences: null },
    });
  });

  it("copies a source's parameters rather than sharing them", () => {
    const dto = sourceDto();
    const source = sourceFromDto(dto);
    expect(source.parameters).toEqual({ listing: "notices" });
    expect(source.parameters).not.toBe(dto.parameters);
  });

  it("maps runs with and without their source, and the trigger of an old run as null", () => {
    expect(crawlRunFromDto(runDto()).sourceKey).toBe(SOURCE_KEY);
    const old = crawlRunFromDto(
      crawlRunDto({ trigger: null, workflow_id: null, finished_at: null }),
    );
    expect(old).toMatchObject({ trigger: null, workflowId: null, finishedAt: null });
  });

  it("maps a stored document, a classified one and its detail with the retries", () => {
    expect(storedDocumentFromDto(documentDto({ doc_type: "statute" }))).toMatchObject({
      documentId: DOCUMENT_ID,
      title: "Example notice 1",
      uploaderType: "statute",
      parserVersion: "pdf@1",
    });
    const read = pipelineDocumentFromDto(pipelineDocumentDto());
    expect(read.readAs).toBe("notification");
    expect(read.classification).toMatchObject({ classifier: "detector@1", route: "extract" });
    expect(read.extraction).toMatchObject({ outcome: "extracted", needsReview: true });
    const bare = pipelineDocumentFromDto(
      pipelineDocumentDto({ read_as: null, classification: null, extraction: null }),
    );
    expect(bare).toMatchObject({ readAs: null, classification: null, extraction: null });
    const detail = documentDetailFromDto(
      documentDetailDto({
        classification: classificationDto({ classifier: "retry", decided_by: ACTOR_ID }),
        retries: [retryDto(), retryDto({ attempt: 2, stage: "extract", doc_type: "circular" })],
      }),
    );
    expect(detail.classification?.decidedBy).toBe(ACTOR_ID);
    expect(detail.retries.map((retry) => [retry.attempt, retry.stage, retry.docType])).toEqual([
      [1, "parse", null],
      [2, "extract", "circular"],
    ]);
  });

  it("maps tasks with their document and resolution", () => {
    const open = taskFromDto(taskDto());
    expect(open).toMatchObject({ taskId: TASK_ID, kind: "manual_parse", resolution: null });
    expect(open.document.status).toBe("failed");
    const resolved = taskFromDto(
      triageTaskDto({
        status: "resolved",
        resolved_by: ACTOR_ID,
        resolved_at: "2000-01-03T00:00:00Z",
        resolution: { relevance: "relevant", doc_type: "circular", route: "extract" },
        note: "Example note on the decision",
      }),
    );
    expect(resolved).toMatchObject({
      kind: "triage",
      status: "resolved",
      resolvedBy: ACTOR_ID,
      resolution: { relevance: "relevant", doc_type: "circular", route: "extract" },
    });
  });

  it("maps an outbox row and a page with its cursor", () => {
    const event = outboxEventFromDto(outboxEventDto());
    expect(event).toMatchObject({ eventId: EVENT_ID, status: "dead", attempts: 8 });
    expect(event.summary).toEqual({ document_id: DOCUMENT_ID, source_key: SOURCE_KEY });
    expect(pageFromDto({ items: [runDto()], next_cursor: "abc" }, crawlRunFromDto)).toMatchObject({
      nextCursor: "abc",
      items: [{ runId: RUN_ID }],
    });
    expect(pageFromDto({ items: [], next_cursor: null }, crawlRunFromDto).nextCursor).toBeNull();
  });

  it("maps the answers of the writes", () => {
    expect(
      fetchStartedFromDto({
        run_id: RUN_ID,
        source_key: SOURCE_KEY,
        trigger: "manual",
        workflow_id: "pipeline-crawl-example_notices-manual-1",
      }),
    ).toEqual({
      runId: RUN_ID,
      sourceKey: SOURCE_KEY,
      trigger: "manual",
      workflowId: "pipeline-crawl-example_notices-manual-1",
    });
    const accepted = retryAcceptedFromDto({
      retry: retryDto(),
      document: documentDetailDto(),
      started: false,
      reclassified: true,
      workflow_id: "pipeline-retry-x-1",
    });
    expect(accepted).toMatchObject({ started: false, reclassified: true, retry: { attempt: 1 } });
    expect(
      requeuedFromDto({ event: outboxEventDto({ status: "pending" }), requeued: true }),
    ).toMatchObject({ requeued: true, event: { status: "pending" } });
    expect(
      taskResolvedFromDto({
        task: taskDto({ status: "resolved" }),
        started: true,
        workflow_id: "w",
      }),
    ).toMatchObject({ started: true, workflowId: "w", task: { status: "resolved" } });
    expect(
      uploadStoredFromDto({ document: documentDto(), duplicate: true, workflow_id: "u" }),
    ).toMatchObject({ duplicate: true, workflowId: "u", document: { documentId: DOCUMENT_ID } });
  });

  it("sends only the changed settings with the reason and the actor", () => {
    expect(sourceEditToDto({ paused: true }, ACTOR_ID, "Example reason to pause")).toEqual({
      actor_id: ACTOR_ID,
      reason: "Example reason to pause",
      paused: true,
    });
    expect(
      sourceEditToDto(
        {
          name: "Example renamed",
          cadenceSeconds: 3600,
          enabled: false,
          parameters: { listing: "circulars" },
        },
        ACTOR_ID,
        "Example reason to edit",
      ),
    ).toEqual({
      actor_id: ACTOR_ID,
      reason: "Example reason to edit",
      name: "Example renamed",
      cadence_seconds: 3600,
      enabled: false,
      parameters: { listing: "circulars" },
    });
  });

  it("writes a transcript's blocks with pages and numbers only where given", () => {
    expect(
      transcriptToDto({
        title: "Example notice",
        blocks: [
          { type: "heading", text: "Example heading", page: 1 },
          { type: "paragraph", number: "1.", text: "Example text.", page: null },
          { type: "paragraph", number: "", text: "Example text, unnumbered.", page: null },
          { type: "table", header: ["S. No.", "Item"], rows: [["1", "Example item"]], page: 2 },
          { type: "table", header: null, rows: [["2", "Example item"]], page: null },
        ],
      }),
    ).toEqual({
      title: "Example notice",
      blocks: [
        { type: "heading", text: "Example heading", page: 1 },
        { type: "paragraph", number: "1.", text: "Example text." },
        { type: "paragraph", text: "Example text, unnumbered." },
        { type: "table", header: ["S. No.", "Item"], rows: [["1", "Example item"]], page: 2 },
        { type: "table", rows: [["2", "Example item"]] },
      ],
    });
  });

  it("writes a triage decision with a type only when relevant", () => {
    expect(triageToDto({ relevance: "relevant", docType: "circular" })).toEqual({
      relevance: "relevant",
      doc_type: "circular",
    });
    expect(triageToDto({ relevance: "irrelevant" })).toEqual({ relevance: "irrelevant" });
  });
});
