import { afterEach, describe, expect, it, vi } from "vitest";
import {
  OBLIGATION_STATUSES,
  closureReasonLabel,
  dueDateText,
  duePhrase,
  evidenceTypeText,
  isObligationActive,
  isObligationOverdue,
  obligationCounts,
  obligationFromDto,
  obligationStatusLabel,
  obligationStatusOptions,
  obligationStatusTone,
  periodText,
  statusChangeLabel,
  statusChanges,
  type ClosureReason,
  type Obligation,
  type ObligationDto,
} from "./obligations";

/** Noon on 15 Oct 2026 in India. */
const NOW = new Date("2026-10-15T06:30:00Z");

/** The end of a due day in India, as the obligation service sends it. */
const dueOn = (day: string) => `${day}T18:29:59Z`;

const DTO: ObligationDto = {
  obligation_id: "obl_1",
  business_id: "biz_1",
  title: "File GSTR-3B for the month",
  status: "open",
  due_at: dueOn("2026-10-20"),
  evidence_type: "filing_acknowledgement",
  steps: ["Reconcile the month's supplies", "Pay the tax due", "File FORM GSTR-3B"],
  rule_version_id: "rv_1",
  decision_id: "dec_1",
  period_label: "2026-08",
  period_start: "2026-08-01",
  period_end: "2026-09-01",
  closed_at: null,
  closed_reason: null,
};

function obligation(overrides: Partial<Obligation> = {}): Obligation {
  return { ...obligationFromDto(DTO), ...overrides };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("obligationFromDto", () => {
  it("maps every field of ObligationOut", () => {
    expect(
      obligationFromDto({
        ...DTO,
        status: "done",
        closed_at: "2026-10-18T05:00:00Z",
        closed_reason: "completed",
      }),
    ).toEqual({
      id: "obl_1",
      businessId: "biz_1",
      title: "File GSTR-3B for the month",
      status: "done",
      dueAt: "2026-10-20T18:29:59Z",
      evidenceType: "filing_acknowledgement",
      steps: ["Reconcile the month's supplies", "Pay the tax due", "File FORM GSTR-3B"],
      ruleVersionId: "rv_1",
      decisionId: "dec_1",
      periodLabel: "2026-08",
      periodStart: "2026-08-01",
      periodEnd: "2026-09-01",
      closedAt: "2026-10-18T05:00:00Z",
      closedReason: "completed",
    });
  });
});

describe("obligation labels and tones", () => {
  it("words and tones every status, and lists them as options in order", () => {
    expect(OBLIGATION_STATUSES.map(obligationStatusLabel)).toEqual([
      "Open",
      "In progress",
      "Done",
      "Waived",
      "Not applicable",
    ]);
    expect(OBLIGATION_STATUSES.map(obligationStatusTone)).toEqual([
      "info",
      "warning",
      "success",
      "neutral",
      "neutral",
    ]);
    expect(obligationStatusOptions()[1]).toEqual({ value: "in_progress", label: "In progress" });
    expect(obligationStatusOptions().map((option) => option.value)).toEqual(OBLIGATION_STATUSES);
  });

  it("words every closure reason", () => {
    const reasons: ClosureReason[] = [
      "completed",
      "waived_by_user",
      "profile_changed",
      "rule_withdrawn",
      "rule_superseded",
    ];
    expect(reasons.map(closureReasonLabel)).toEqual([
      "Completed",
      "Waived by the business",
      "Closed when the business profile changed",
      "Closed when the rule was withdrawn",
      "Closed when a newer version of the rule replaced it",
    ]);
  });
});

describe("status changes", () => {
  it("starts an open obligation or marks it done, and only marks one in progress done", () => {
    expect(statusChanges("open")).toEqual(["in_progress", "done"]);
    expect(statusChanges("in_progress")).toEqual(["done"]);
    expect(statusChanges("done")).toEqual([]);
    expect(statusChanges("waived")).toEqual([]);
    expect(statusChanges("closed_not_applicable")).toEqual([]);
    expect(statusChangeLabel("in_progress")).toBe("Start work");
    expect(statusChangeLabel("done")).toBe("Mark as done");
  });

  it("treats open and in-progress obligations as still to be done", () => {
    expect(OBLIGATION_STATUSES.filter(isObligationActive)).toEqual(["open", "in_progress"]);
  });
});

describe("isObligationOverdue", () => {
  it("is true for an active obligation whose due day in India has passed", () => {
    expect(isObligationOverdue(obligation({ dueAt: dueOn("2026-10-14") }), NOW)).toBe(true);
    expect(
      isObligationOverdue(obligation({ status: "in_progress", dueAt: dueOn("2026-09-01") }), NOW),
    ).toBe(true);
  });

  it("is false on the due day itself, before it, once closed and without a due date", () => {
    expect(isObligationOverdue(obligation({ dueAt: dueOn("2026-10-15") }), NOW)).toBe(false);
    expect(isObligationOverdue(obligation(), NOW)).toBe(false);
    expect(
      isObligationOverdue(obligation({ status: "done", dueAt: dueOn("2026-09-01") }), NOW),
    ).toBe(false);
    expect(isObligationOverdue(obligation({ dueAt: null }), NOW)).toBe(false);
  });

  it("measures against the current time by default", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    expect(isObligationOverdue(obligation({ dueAt: dueOn("2026-10-14") }))).toBe(true);
    expect(isObligationOverdue(obligation({ dueAt: dueOn("2026-10-16") }))).toBe(false);
  });
});

describe("due wording", () => {
  it("formats the due day in India, or says there is none", () => {
    expect(dueDateText(obligation())).toBe("20 Oct 2026");
    expect(dueDateText(obligation({ dueAt: null }))).toBe("No due date");
  });

  it("says how the due day relates to today", () => {
    const phrase = (day: string) => duePhrase(obligation({ dueAt: dueOn(day) }), NOW);
    expect(phrase("2026-10-15")).toBe("Due today");
    expect(phrase("2026-10-16")).toBe("Due tomorrow");
    expect(phrase("2026-10-20")).toBe("Due in 5 days");
    expect(phrase("2026-10-14")).toBe("Overdue by 1 day");
    expect(phrase("2026-10-12")).toBe("Overdue by 3 days");
  });

  it("says nothing for a closed obligation or one without a due date", () => {
    expect(duePhrase(obligation({ status: "waived", dueAt: dueOn("2026-10-12") }), NOW)).toBeNull();
    expect(duePhrase(obligation({ dueAt: null }), NOW)).toBeNull();
  });

  it("uses the current time by default", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    expect(duePhrase(obligation())).toBe("Due in 5 days");
  });
});

describe("periodText", () => {
  it("words the period with its first and last day", () => {
    expect(periodText(obligation())).toBe("Period 2026-08: 1 Aug 2026 to 31 Aug 2026");
    expect(
      periodText(
        obligation({
          periodLabel: "2026-27 Q1",
          periodStart: "2026-04-01",
          periodEnd: "2026-07-01",
        }),
      ),
    ).toBe("Period 2026-27 Q1: 1 Apr 2026 to 30 Jun 2026");
  });

  it("gives the label alone without dates, and nothing for a one-off duty", () => {
    expect(periodText(obligation({ periodStart: null }))).toBe("Period 2026-08");
    expect(periodText(obligation({ periodEnd: null }))).toBe("Period 2026-08");
    expect(periodText(obligation({ periodLabel: null }))).toBeNull();
  });
});

describe("evidenceTypeText", () => {
  it("reads the evidence code as words, or says the rule names none", () => {
    expect(evidenceTypeText("filing_acknowledgement")).toBe("Filing acknowledgement");
    expect(evidenceTypeText("gst_challan")).toBe("GST challan");
    expect(evidenceTypeText("")).toBe("Not specified");
    expect(evidenceTypeText("  ")).toBe("Not specified");
  });
});

describe("obligationCounts", () => {
  it("counts all, open, in progress, overdue and done obligations", () => {
    expect(
      obligationCounts(
        [
          obligation({ id: "1" }),
          obligation({ id: "2", dueAt: dueOn("2026-10-10") }),
          obligation({ id: "3", status: "in_progress", dueAt: dueOn("2026-10-11") }),
          obligation({ id: "4", status: "done", dueAt: dueOn("2026-09-01") }),
          obligation({ id: "5", status: "waived" }),
        ],
        NOW,
      ),
    ).toEqual({ total: 5, open: 2, inProgress: 1, overdue: 2, done: 1 });
  });

  it("is all zeros for no obligations, measured against now by default", () => {
    expect(obligationCounts([])).toEqual({
      total: 0,
      open: 0,
      inProgress: 0,
      overdue: 0,
      done: 0,
    });
  });
});
