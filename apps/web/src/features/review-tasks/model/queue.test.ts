import { describe, expect, it } from "vitest";
import { queuedTaskFromDto } from "@/entities/rule-version/mappers";
import { EXAMPLE_ANALYST_ID, EXAMPLE_OTHER_ANALYST_ID } from "@/test/rule-version-fixture";
import {
  EXAMPLE_CANDIDATE_TASK_ID,
  EXAMPLE_TASK_ID,
  queuedCandidateTaskDto,
  queuedTaskDto,
} from "@/test/review-task-fixture";
import {
  decisionLabel,
  emptyText,
  kindChips,
  percent,
  queueHref,
  queueRow,
  queueView,
  readQueueFilter,
  regulatorChips,
  samplingNote,
  statusChips,
  taskKindLabel,
  taskStatusLabel,
  type QueueFilter,
} from "./queue";

const OPEN: QueueFilter = { status: "open", kind: null, regulator: null, cursor: null };

describe("readQueueFilter", () => {
  it("reads open as the default and every filter the address gives", () => {
    expect(readQueueFilter({})).toEqual(OPEN);
    expect(
      readQueueFilter({
        status: "claimed",
        kind: "candidate",
        regulator: " Example_Regulator ",
        cursor: "example-cursor",
      }),
    ).toEqual({
      status: "claimed",
      kind: "candidate",
      regulator: "example_regulator",
      cursor: "example-cursor",
    });
    expect(readQueueFilter({ status: "all" }).status).toBe("all");
  });

  it("reads a value out of shape as no filter", () => {
    expect(
      readQueueFilter({
        status: "closed",
        kind: ["sample", "seed"],
        regulator: "x".repeat(41),
        cursor: "c".repeat(513),
      }),
    ).toEqual(OPEN);
  });
});

describe("the chips and links", () => {
  it("keeps the other filters in each chip and starts from the first page", () => {
    const filter: QueueFilter = {
      status: "open",
      kind: "seed",
      regulator: "example_regulator",
      cursor: "example-cursor",
    };
    expect(statusChips(filter).map((chip) => [chip.key, chip.href, chip.current])).toEqual([
      ["open", "/admin/review?kind=seed&regulator=example_regulator", true],
      ["claimed", "/admin/review?status=claimed&kind=seed&regulator=example_regulator", false],
      ["decided", "/admin/review?status=decided&kind=seed&regulator=example_regulator", false],
      ["all", "/admin/review?status=all&kind=seed&regulator=example_regulator", false],
    ]);
    expect(kindChips(filter).map((chip) => [chip.label, chip.current])).toEqual([
      ["Every kind", false],
      ["Seed draft", true],
      ["Rule candidate", false],
    ]);
    expect(
      regulatorChips({ ...filter, regulator: "example_unlisted" }, ["Example_Regulator"]).map(
        (chip) => [chip.key, chip.current, chip.href],
      ),
    ).toEqual([
      ["any", false, "/admin/review?kind=seed"],
      ["example_regulator", false, "/admin/review?kind=seed&regulator=example_regulator"],
      ["example_unlisted", true, "/admin/review?kind=seed&regulator=example_unlisted"],
    ]);
    expect(queueHref(OPEN)).toBe("/admin/review");
  });

  it("words the statuses, kinds and decisions, and a value it does not know as sent", () => {
    expect(taskStatusLabel("claimed")).toBe("Claimed");
    expect(taskStatusLabel("all")).toBe("Every status");
    expect(taskStatusLabel("example_state")).toBe("Example state");
    expect(taskKindLabel("candidate")).toBe("Rule candidate");
    expect(taskKindLabel("example_kind")).toBe("Example kind");
    expect(decisionLabel("return")).toBe("Returned");
    expect(decisionLabel("example_decision")).toBe("Example decision");
    expect(percent(0.875)).toBe("88%");
    expect(percent(1.5)).toBe("100%");
  });
});

describe("queueRow", () => {
  it("shows a seed task's version, approvals and claim, marking the signed-in analyst's", () => {
    const row = queueRow(
      queuedTaskFromDto(
        queuedTaskDto({
          status: "claimed",
          claimed_by: EXAMPLE_ANALYST_ID,
          claimed_at: "2000-05-01T05:00:00Z",
          high_impact: true,
          approvals: 1,
          required_approvals: 2,
        }),
      ),
      EXAMPLE_ANALYST_ID,
    );
    expect(row).toMatchObject({
      taskId: EXAMPLE_TASK_ID,
      href: `/admin/review/${EXAMPLE_TASK_ID}`,
      kindLabel: "Seed draft",
      ruleLabel: "example_rule v1",
      suggested: false,
      versionStatus: "draft",
      approvals: "1 of 2 approvals",
      highImpact: true,
      candidate: null,
      statusLabel: "Claimed",
      claimedBy: { userId: EXAMPLE_ANALYST_ID, you: true },
      claimedAt: "1 May 2000, 10:30 am IST",
      mine: true,
      claimable: false,
      decision: null,
    });
  });

  it("shows a candidate task's suggested key and its extraction before drafting", () => {
    const row = queueRow(queuedTaskFromDto(queuedCandidateTaskDto()), EXAMPLE_ANALYST_ID);
    expect(row).toMatchObject({
      taskId: EXAMPLE_CANDIDATE_TASK_ID,
      ruleLabel: "example_suggested_rule",
      suggested: true,
      versionStatus: null,
      claimable: true,
      mine: false,
      candidate: {
        outcome: "Extracted",
        unparseable: false,
        confidence: "Confidence 82%",
        issues: "Issues found: 2",
        needsReview: true,
      },
    });
    const unparseable = queueRow(
      queuedTaskFromDto(
        queuedCandidateTaskDto({
          rule_key: null,
          candidate: {
            ...(queuedCandidateTaskDto().candidate as NonNullable<
              ReturnType<typeof queuedCandidateTaskDto>["candidate"]
            >),
            outcome: "unparseable",
          },
        }),
      ),
      EXAMPLE_ANALYST_ID,
    );
    expect(unparseable.ruleLabel).toBeNull();
    expect(unparseable.candidate).toMatchObject({
      outcome: "Unparseable: no candidate, drafted by hand",
      unparseable: true,
    });
  });

  it("names who decided a task", () => {
    const row = queueRow(
      queuedTaskFromDto(
        queuedTaskDto({
          status: "decided",
          decision: "reject",
          decided_by: EXAMPLE_OTHER_ANALYST_ID,
          decided_at: "2000-05-02T06:00:00Z",
          note: "Example why",
        }),
      ),
      EXAMPLE_ANALYST_ID,
    );
    expect(row.decision).toEqual({
      label: "Rejected",
      by: { userId: EXAMPLE_OTHER_ANALYST_ID, you: false },
      at: "2 May 2000, 11:30 am IST",
      note: "Example why",
    });
  });
});

describe("queueView", () => {
  it("links the next page with the rulebook's cursor and the first page from a later one", () => {
    const tasks = [queuedTaskFromDto(queuedTaskDto())];
    expect(queueView(OPEN, tasks, "next-cursor", EXAMPLE_ANALYST_ID)).toMatchObject({
      nextHref: "/admin/review?cursor=next-cursor",
      firstHref: null,
    });
    expect(
      queueView({ ...OPEN, status: "all", cursor: "some" }, tasks, null, EXAMPLE_ANALYST_ID),
    ).toMatchObject({ nextHref: null, firstHref: "/admin/review?status=all" });
  });

  it("says why a page is empty in its own words", () => {
    expect(emptyText(OPEN).title).toBe("No task waits for a claim");
    expect(emptyText({ ...OPEN, status: "claimed" }).title).toBe("No task is claimed");
    expect(emptyText({ ...OPEN, status: "decided" }).title).toBe("No task is decided yet");
    expect(emptyText({ ...OPEN, status: "all" }).title).toBe("The queue holds no task");
    expect(emptyText({ ...OPEN, kind: "seed" }).title).toBe("No task matches these filters");
    expect(emptyText({ ...OPEN, cursor: "c" }).title).toBe("No more tasks");
  });
});

describe("samplingNote", () => {
  it("tells a reviewer or an admin what review sampling waits for, and nobody else", () => {
    expect(samplingNote(["reviewer"])).toEqual({
      title: "Review sampling",
      waitingFor: expect.stringContaining("POST /v1/rulebook/review/samples") as string,
    });
    expect(samplingNote(["analyst"])).toBeNull();
  });
});
