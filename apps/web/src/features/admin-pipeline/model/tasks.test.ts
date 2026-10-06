import { describe, expect, it } from "vitest";
import { taskFromDto } from "@/entities/pipeline/mappers";
import { TASK_KINDS, TASK_STATUSES } from "@/entities/pipeline/types";
import { ACTOR_ID, DOCUMENT_ID, TASK_ID, taskDto, triageTaskDto } from "@/test/pipeline-fixture";
import { RESOLVE_FIELDS } from "../ui/pipeline-shared";
import {
  kindChips,
  parseResolution,
  readTaskQuery,
  statusChips,
  taskCard,
  taskKindLabel,
  taskStatusLabel,
  tasksHref,
  tasksView,
} from "./tasks";

const REASON = "Example reason of enough length";

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(values)) data.set(name, value);
  return data;
}

describe("the task list's query", () => {
  it("reads open tasks of every kind by default, and every status when asked", () => {
    expect(readTaskQuery({})).toEqual({ status: "open", kind: null, cursor: null });
    expect(readTaskQuery({ status: "every", kind: "triage", cursor: "c1" })).toEqual({
      status: null,
      kind: "triage",
      cursor: "c1",
    });
    expect(readTaskQuery({ status: "nope", kind: "nope", cursor: "x".repeat(513) })).toEqual({
      status: "open",
      kind: null,
      cursor: null,
    });
    expect(tasksHref({ status: "open", kind: null, cursor: null })).toBe("/admin/pipeline/tasks");
    expect(tasksHref({ status: null, kind: "manual_parse", cursor: null }, "c2")).toBe(
      "/admin/pipeline/tasks?status=every&kind=manual_parse&cursor=c2",
    );
  });

  it("offers chips that keep the other filter", () => {
    const filter = { status: "resolved" as const, kind: "triage" as const, cursor: "c" };
    expect(statusChips(filter).map((chip) => [chip.key, chip.href, chip.current])).toEqual([
      ["open", "/admin/pipeline/tasks?kind=triage", false],
      ["resolved", "/admin/pipeline/tasks?status=resolved&kind=triage", true],
      ["dismissed", "/admin/pipeline/tasks?status=dismissed&kind=triage", false],
      ["every", "/admin/pipeline/tasks?status=every&kind=triage", false],
    ]);
    expect(kindChips(filter).map((chip) => [chip.key, chip.current])).toEqual([
      ["every", false],
      ["manual_parse", false],
      ["triage", true],
    ]);
    for (const status of TASK_STATUSES) expect(taskStatusLabel(status)).not.toBe(status);
    for (const kind of TASK_KINDS) expect(taskKindLabel(kind)).not.toBe(kind);
    expect(taskStatusLabel("example_new")).toBe("Example new");
    expect(taskKindLabel("example_new")).toBe("Example new");
  });
});

describe("taskCard and tasksView", () => {
  it("words an open task with its document's links", () => {
    const card = taskCard(taskFromDto(taskDto()), null);
    expect(card).toMatchObject({
      taskId: TASK_ID,
      kindLabel: "Manual parse",
      statusLabel: "Open",
      statusTone: "warning",
      document: {
        href: `/admin/pipeline/documents/${DOCUMENT_ID}`,
        rawHref: `/api-bff/pipeline/documents/${DOCUMENT_ID}/raw`,
        status: "failed",
      },
      closed: null,
    });
  });

  it("words a closed task with who closed it, and pages the list", () => {
    const resolved = taskCard(
      taskFromDto(
        triageTaskDto({
          status: "resolved",
          resolved_by: ACTOR_ID,
          resolved_at: "2000-01-03T00:00:00Z",
          note: "Example note",
          claimed_by: ACTOR_ID,
        }),
      ),
      ACTOR_ID,
    );
    expect(resolved.closed).toMatchObject({ by: "you", note: "Example note" });
    expect(resolved.claimedBy).toBe("you");
    const closedByPipeline = taskCard(taskFromDto(taskDto({ status: "resolved" })), null);
    expect(closedByPipeline.closed).toMatchObject({ by: null, at: null });
    const view = tasksView(
      { status: "open", kind: null, cursor: "c1" },
      { items: [taskFromDto(taskDto())], nextCursor: "c2" },
      null,
    );
    expect(view.nextHref).toBe("/admin/pipeline/tasks?cursor=c2");
    expect(view.firstHref).toBe("/admin/pipeline/tasks");
  });
});

describe("parseResolution", () => {
  it("reads a manual parse's transcript and a triage's decision", () => {
    const transcript = parseResolution(
      "manual_parse",
      form({
        [RESOLVE_FIELDS.title]: " Example title ",
        [RESOLVE_FIELDS.transcript]: "# Example heading\n\n1. Example text.",
        [RESOLVE_FIELDS.reason]: REASON,
      }),
    );
    expect(transcript).toMatchObject({
      ok: true,
      reason: REASON,
      resolution: {
        transcript: {
          title: "Example title",
          blocks: [{ type: "heading" }, { type: "paragraph", number: "1." }],
        },
      },
    });
    expect(
      parseResolution(
        "triage",
        form({
          [RESOLVE_FIELDS.relevance]: "relevant",
          [RESOLVE_FIELDS.docType]: "circular",
          [RESOLVE_FIELDS.reason]: REASON,
        }),
      ),
    ).toEqual({
      ok: true,
      reason: REASON,
      resolution: { triage: { relevance: "relevant", docType: "circular" } },
    });
    expect(
      parseResolution(
        "triage",
        form({
          [RESOLVE_FIELDS.relevance]: "irrelevant",
          [RESOLVE_FIELDS.docType]: "circular",
          [RESOLVE_FIELDS.reason]: REASON,
        }),
      ),
    ).toEqual({ ok: true, reason: REASON, resolution: { triage: { relevance: "irrelevant" } } });
  });

  it("names what is missing or wrong", () => {
    const transcript = parseResolution(
      "manual_parse",
      form({
        [RESOLVE_FIELDS.title]: "x".repeat(501),
        [RESOLVE_FIELDS.transcript]: "",
        [RESOLVE_FIELDS.reason]: "short",
      }),
    );
    expect(transcript.ok || Object.keys(transcript.fieldErrors).sort()).toEqual([
      "reason",
      "title",
      "transcript",
    ]);
    const relevant = parseResolution(
      "triage",
      form({ [RESOLVE_FIELDS.relevance]: "relevant", [RESOLVE_FIELDS.reason]: REASON }),
    );
    expect(relevant.ok || Object.keys(relevant.fieldErrors)).toEqual(["doc_type"]);
    const none = parseResolution("triage", form({ [RESOLVE_FIELDS.reason]: REASON }));
    expect(none.ok || Object.keys(none.fieldErrors)).toEqual(["relevance"]);
  });
});
