import { describe, expect, it } from "vitest";
import { listedObligationFromDto, ruleVersionFactsFromDto } from "@/entities/obligation/mappers";
import { NOW, dueAt, listedObligationDto, ruleVersionFactsDto } from "@/test/obligation-fixture";
import {
  ALL_STATUSES,
  TO_DO,
  closedText,
  closureReasonLabel,
  dueDateText,
  dueDay,
  duePhrase,
  evidenceTypeText,
  isObligationActive,
  isObligationOverdue,
  isStatusFilter,
  obligationStatusLabel,
  obligationStatusTone,
  periodText,
  reviewState,
  statusActionLabel,
  statusActions,
  statusFilterOptions,
  statusesOf,
} from "./obligations";

function obligation(overrides: Parameters<typeof listedObligationDto>[0] = {}) {
  return listedObligationFromDto(listedObligationDto(overrides));
}

describe("status wording", () => {
  it("labels and tones every status, and words the closures and the actions", () => {
    expect(obligationStatusLabel("in_progress")).toBe("In progress");
    expect(obligationStatusTone("done")).toBe("success");
    expect(obligationStatusTone("open")).toBe("info");
    expect(closureReasonLabel("waived_by_user")).toBe("Waived by the business");
    expect(statusActionLabel("complete")).toBe("Mark as done");
    expect(statusActionLabel("waive")).toBe("Waive");
  });

  it("offers the changes the status allows and none once closed", () => {
    expect(statusActions("open")).toEqual(["start", "complete", "waive"]);
    expect(statusActions("in_progress")).toEqual(["complete", "waive"]);
    for (const status of ["done", "waived", "closed_not_applicable"] as const) {
      expect(statusActions(status)).toEqual([]);
      expect(isObligationActive(status)).toBe(false);
    }
  });
});

describe("due dates in India", () => {
  it("reads the due day in IST and says how it relates to today", () => {
    const item = obligation({ due_at: dueAt("2000-01-13") });
    expect(dueDay(item.dueAt as string)).toBe("2000-01-13");
    expect(dueDateText(item)).toBe("13 Jan 2000");
    expect(duePhrase(item, NOW)).toBe("Due in 3 days");
    expect(duePhrase(obligation({ due_at: dueAt("2000-01-10") }), NOW)).toBe("Due today");
    expect(duePhrase(obligation({ due_at: dueAt("2000-01-11") }), NOW)).toBe("Due tomorrow");
    expect(duePhrase(obligation({ due_at: dueAt("2000-01-09") }), NOW)).toBe("Overdue by 1 day");
    expect(duePhrase(obligation({ due_at: dueAt("2000-01-05") }), NOW)).toBe("Overdue by 5 days");
  });

  it("calls an active obligation past its day overdue, never a closed one or one without a date", () => {
    expect(isObligationOverdue(obligation({ due_at: dueAt("2000-01-09") }), NOW)).toBe(true);
    expect(
      isObligationOverdue(obligation({ due_at: dueAt("2000-01-09"), status: "done" }), NOW),
    ).toBe(false);
    const undated = obligation({ due_at: null });
    expect(isObligationOverdue(undated, NOW)).toBe(false);
    expect(dueDateText(undated)).toBe("No due date");
    expect(duePhrase(undated, NOW)).toBeNull();
    expect(duePhrase(obligation({ status: "waived" }), NOW)).toBeNull();
  });
});

describe("period, evidence and closure", () => {
  it("words the half-open period with its last day", () => {
    expect(periodText(obligation())).toBe("Period 2000-01: 1 Jan 2000 to 31 Jan 2000");
    expect(periodText(obligation({ period_start: null, period_end: null }))).toBe("Period 2000-01");
    expect(periodText(obligation({ period_label: null }))).toBeNull();
  });

  it("humanises the evidence and says when the rule names none", () => {
    expect(evidenceTypeText("example_acknowledgement")).toBe("Example acknowledgement");
    expect(evidenceTypeText("  ")).toBe("Not specified");
  });

  it("says when and why an obligation closed", () => {
    expect(closedText(obligation())).toBeNull();
    expect(
      closedText(
        obligation({
          status: "done",
          closed_at: "2000-01-08T05:00:00Z",
          closed_reason: "completed",
        }),
      ),
    ).toBe("Completed on 8 Jan 2000");
    expect(closedText(obligation({ closed_at: "2000-01-08T05:00:00Z" }))).toBe("8 Jan 2000");
  });
});

describe("the status filter", () => {
  it("knows its values and maps them to the service's statuses", () => {
    expect(isStatusFilter(ALL_STATUSES)).toBe(true);
    expect(isStatusFilter(TO_DO)).toBe(true);
    expect(isStatusFilter("waived")).toBe(true);
    expect(isStatusFilter("overdue")).toBe(false);
    expect(statusesOf(ALL_STATUSES)).toEqual([]);
    expect(statusesOf(TO_DO)).toEqual(["open", "in_progress"]);
    expect(statusesOf("done")).toEqual(["done"]);
    expect(statusFilterOptions().map((option) => option.value)).toEqual([
      "all",
      "todo",
      "open",
      "in_progress",
      "done",
      "waived",
      "closed_not_applicable",
    ]);
  });
});

describe("reviewState", () => {
  it("tells a reviewed rule from a seed rule still to review and from an unknown one", () => {
    expect(reviewState(ruleVersionFactsFromDto(ruleVersionFactsDto()))).toEqual({
      reviewed: false,
      label: "Not yet reviewed",
      tone: "warning",
    });
    expect(
      reviewState(
        ruleVersionFactsFromDto(ruleVersionFactsDto({ seed_status: "reviewed", reviewed: true })),
      ).label,
    ).toBe("Reviewed");
    expect(reviewState(null)).toEqual({
      reviewed: false,
      label: "Review not known yet",
      tone: "neutral",
    });
  });
});
