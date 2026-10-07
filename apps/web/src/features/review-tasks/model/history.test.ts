import { describe, expect, it } from "vitest";
import { auditEntryFromDto, reviewTaskFromDto } from "@/entities/rule-version/mappers";
import {
  EXAMPLE_ANALYST_ID,
  EXAMPLE_OTHER_ANALYST_ID,
  EXAMPLE_OTHER_VERSION_ID,
} from "@/test/rule-version-fixture";
import {
  EXAMPLE_NEXT_TASK_ID,
  EXAMPLE_TASK_ID,
  auditEntryDto,
  reviewTaskDto,
} from "@/test/review-task-fixture";
import { actionLabel, historyView } from "./history";

describe("historyView", () => {
  it("lists the audit newest first with each move, actor and note", () => {
    const view = historyView(
      [
        auditEntryFromDto(auditEntryDto()),
        auditEntryFromDto(
          auditEntryDto({
            decision_id: "00000000-0000-4000-8000-0000000007d2",
            action: "submitted",
            from_status: "draft",
            to_status: "in_review",
            actor_id: EXAMPLE_OTHER_ANALYST_ID,
            note: "",
            decided_at: "2000-05-01T06:00:00Z",
          }),
        ),
        auditEntryFromDto(
          auditEntryDto({
            decision_id: "00000000-0000-4000-8000-0000000007d3",
            action: "superseded",
            from_status: "published",
            to_status: "superseded",
            actor_id: null,
            caused_by_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
            decided_at: "2000-05-01T04:00:00Z",
          }),
        ),
      ],
      [reviewTaskFromDto(reviewTaskDto())],
      EXAMPLE_TASK_ID,
      EXAMPLE_ANALYST_ID,
    );
    expect(view.audit.map((row) => [row.action, row.move])).toEqual([
      ["Submitted for review", "Draft to In review"],
      ["Edited", "Draft"],
      ["Superseded", "Published to Superseded"],
    ]);
    expect(view.audit[0]?.actor).toEqual({ userId: EXAMPLE_OTHER_ANALYST_ID, you: false });
    expect(view.audit[1]).toMatchObject({
      actor: { userId: EXAMPLE_ANALYST_ID, you: true },
      note: "Example note: title",
      at: "1 May 2000, 10:30 am IST",
      causedBy: null,
    });
    expect(view.audit[2]).toMatchObject({
      actor: null,
      causedBy: {
        ruleVersionId: EXAMPLE_OTHER_VERSION_ID,
        href: `/admin/rulebook/versions/${EXAMPLE_OTHER_VERSION_ID}`,
      },
    });
  });

  it("lists every task oldest first, the current one marked and each other one linked", () => {
    const view = historyView(
      [],
      [
        reviewTaskFromDto(
          reviewTaskDto({
            status: "decided",
            claimed_by: EXAMPLE_ANALYST_ID,
            claimed_at: "2000-05-01T05:00:00Z",
            decision: "return",
            decided_by: EXAMPLE_OTHER_ANALYST_ID,
            decided_at: "2000-05-01T07:00:00Z",
            note: "Example rework",
          }),
        ),
        reviewTaskFromDto(reviewTaskDto({ task_id: EXAMPLE_NEXT_TASK_ID })),
      ],
      EXAMPLE_NEXT_TASK_ID,
      EXAMPLE_ANALYST_ID,
    );
    expect(view.tasks).toEqual([
      {
        taskId: EXAMPLE_TASK_ID,
        href: `/admin/review/${EXAMPLE_TASK_ID}`,
        current: false,
        kind: "Seed draft",
        status: "Decided",
        opened: "1 May 2000, 10:00 am IST",
        claimed: { by: { userId: EXAMPLE_ANALYST_ID, you: true }, at: "1 May 2000, 10:30 am IST" },
        decision: {
          label: "Returned",
          by: { userId: EXAMPLE_OTHER_ANALYST_ID, you: false },
          at: "1 May 2000, 12:30 pm IST",
          note: "Example rework",
        },
      },
      {
        taskId: EXAMPLE_NEXT_TASK_ID,
        href: `/admin/review/${EXAMPLE_NEXT_TASK_ID}`,
        current: true,
        kind: "Seed draft",
        status: "Open",
        opened: "1 May 2000, 10:00 am IST",
        claimed: null,
        decision: null,
      },
    ]);
  });

  it("words an action it does not know as sent", () => {
    expect(actionLabel("published")).toBe("Published");
    expect(actionLabel("example_action")).toBe("Example action");
  });
});
