import { describe, expect, it } from "vitest";
import { documentDetailFromDto } from "@/entities/pipeline/mappers";
import { RETRY_STAGES } from "@/entities/pipeline/types";
import { ACTOR_ID, DOCUMENT_ID, documentDetailDto, retryDto } from "@/test/pipeline-fixture";
import { RETRY_FIELDS } from "../ui/pipeline-shared";
import { documentPageView, parseRetry, reasonOf, retryRow, stageLabel } from "./document";

const REASON = "Example reason of enough length";

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(values)) data.set(name, value);
  return data;
}

describe("the document's page", () => {
  it("words the record, its classification and its retries, the latest first", () => {
    const view = documentPageView(
      documentDetailFromDto(
        documentDetailDto({
          retries: [
            retryDto(),
            retryDto({ attempt: 2, stage: "classify", doc_type: "circular", requested_by: null }),
          ],
        }),
      ),
      ACTOR_ID,
    );
    expect(view).toMatchObject({
      documentId: DOCUMENT_ID,
      title: "Example notice 1",
      rawHref: `/api-bff/pipeline/documents/${DOCUMENT_ID}/raw`,
      sourceHref: "/admin/sources/example_notices",
      readAs: "Notification",
      readAsType: "notification",
      uploaderType: null,
      parser: "pdf@1",
      classification: { by: "The detector (detector@1)" },
      extraction: { outcome: "A rule candidate" },
    });
    expect(
      view.retries.map((retry) => [retry.attempt, retry.stage, retry.docType, retry.requestedBy]),
    ).toEqual([
      [2, "Classify", "Circular", null],
      [1, "Parse", null, "you"],
    ]);
    expect(retryRow(documentDetailFromDto(documentDetailDto()).retries[0]!, null).requestedBy).toBe(
      ACTOR_ID,
    );
    const bare = documentPageView(
      documentDetailFromDto(
        documentDetailDto({
          published_on: null,
          parser_version: "",
          doc_type: "statute",
          classification: null,
          extraction: null,
          retries: [],
        }),
      ),
      null,
    );
    expect(bare).toMatchObject({
      published: null,
      parser: null,
      uploaderType: "Statute",
      classification: null,
      extraction: null,
      retries: [],
    });
  });

  it("names every stage, and humanises a new one", () => {
    for (const stage of RETRY_STAGES) expect(stageLabel(stage), stage).not.toBe(stage);
    expect(stageLabel("example_stage")).toBe("Example stage");
  });
});

describe("parseRetry", () => {
  it("takes a stage, an optional type and the reason", () => {
    expect(
      parseRetry(
        form({
          [RETRY_FIELDS.stage]: "classify",
          [RETRY_FIELDS.docType]: "circular",
          [RETRY_FIELDS.reason]: ` ${REASON} `,
        }),
      ),
    ).toEqual({ ok: true, stage: "classify", docType: "circular", reason: REASON });
    expect(
      parseRetry(form({ [RETRY_FIELDS.stage]: "parse", [RETRY_FIELDS.reason]: REASON })),
    ).toEqual({
      ok: true,
      stage: "parse",
      docType: null,
      reason: REASON,
    });
  });

  it("names a missing stage, an unknown type and a short reason", () => {
    const parsed = parseRetry(
      form({
        [RETRY_FIELDS.stage]: "fetch",
        [RETRY_FIELDS.docType]: "memo",
        [RETRY_FIELDS.reason]: "short",
      }),
    );
    expect(parsed.ok || Object.keys(parsed.fieldErrors).sort()).toEqual([
      "doc_type",
      "reason",
      "stage",
    ]);
    expect(
      parseRetry(
        form({
          [RETRY_FIELDS.stage]: "parse",
          [RETRY_FIELDS.docType]: "memo",
          [RETRY_FIELDS.reason]: REASON,
        }),
      ).ok,
    ).toBe(false);
    expect(reasonOf(form({ reason: "x".repeat(2001) }), "reason").ok).toBe(false);
  });
});
