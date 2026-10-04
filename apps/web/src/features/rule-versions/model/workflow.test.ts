import { describe, expect, it } from "vitest";
import { lifecycleFromDto, publicationFromDto } from "@/entities/rule-version/mappers";
import { lifecycleDto, publicationDto } from "@/test/rule-version-fixture";
import { isWorkflowStep, parseStepForm, stepResult, stepsFor } from "./workflow";

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) data.append(key, value);
  return data;
}

describe("stepsFor", () => {
  it("offers the steps each status allows", () => {
    expect(stepsFor("draft")).toEqual(["submit"]);
    expect(stepsFor("in_review")).toEqual(["approve", "return"]);
    expect(stepsFor("approved")).toEqual(["publish", "return"]);
    expect(stepsFor("published")).toEqual(["withdraw"]);
    expect(stepsFor("superseded")).toEqual([]);
    expect(stepsFor("withdrawn")).toEqual([]);
    expect(stepsFor("example")).toEqual([]);
    expect(isWorkflowStep("approve")).toBe(true);
    expect(isWorkflowStep("delete")).toBe(false);
  });
});

describe("parseStepForm", () => {
  it("reads a step, its note and the high-impact box", () => {
    expect(
      parseStepForm(form({ step: "submit", note: " Example note ", high_impact: "on" })),
    ).toEqual({
      ok: true,
      step: "submit",
      note: "Example note",
      highImpact: true,
    });
    expect(parseStepForm(form({ step: "approve" }))).toEqual({
      ok: true,
      step: "approve",
      note: "",
      highImpact: false,
    });
  });

  it("refuses an unknown step and a note longer than the rulebook keeps", () => {
    expect(parseStepForm(form({ step: "delete" }))).toEqual({
      ok: false,
      fieldErrors: { step: ["Choose a step of the workflow."] },
    });
    expect(parseStepForm(form({ step: "publish", note: "x".repeat(2001) }))).toEqual({
      ok: false,
      fieldErrors: { note: ["A note has at most 2000 characters."] },
    });
  });

  it("asks for a reason of ten characters or more to return or withdraw", () => {
    for (const step of ["return", "withdraw"]) {
      expect(parseStepForm(form({ step, note: "Too short" }))).toEqual({
        ok: false,
        fieldErrors: { note: ["Give a reason of at least 10 characters."] },
      });
      expect(parseStepForm(form({ step, note: "Example reason" }))).toMatchObject({ ok: true });
    }
  });
});

describe("stepResult", () => {
  it("keeps the lifecycle of a step and the effects of a publication as plain data", () => {
    const approved = stepResult("approve", lifecycleFromDto(lifecycleDto()));
    expect(approved.publication).toBeNull();
    expect(approved.lifecycle.approvedBy).toHaveLength(1);
    const published = stepResult("publish", publicationFromDto(publicationDto()));
    expect(published.publication).toMatchObject({
      correlationId: "00000000-0000-4000-8000-0000000000e2",
      replacements: [{ movesTo: "superseded" }],
      deadlineChanges: [],
      attributeKeys: ["example_band", "example_kind"],
    });
    expect(Object.keys(published.lifecycle)).not.toContain("replacements");
  });
});
