import { describe, expect, it } from "vitest";
import { onboardingFromDto } from "@/entities/business/mappers";
import { ONBOARDING_DTO } from "@/test/business-fixture";
import { onboardingProgress } from "./progress";

describe("onboardingProgress", () => {
  it("counts answered of total with a whole percentage and the words for the bar", () => {
    expect(onboardingProgress(onboardingFromDto(ONBOARDING_DTO))).toEqual({
      answered: 4,
      total: 8,
      percent: 50,
      text: "4 of 8 answered",
      complete: false,
    });
  });

  it("clamps what the service counts and reads an empty checklist as complete", () => {
    const base = onboardingFromDto(ONBOARDING_DTO);
    expect(onboardingProgress({ ...base, answered: 9, total: 8 }).answered).toBe(8);
    expect(onboardingProgress({ ...base, answered: -1 }).percent).toBe(0);
    const empty = onboardingProgress({
      ...base,
      answered: 0,
      total: 0,
      complete: true,
      next: null,
    });
    expect(empty).toMatchObject({ percent: 100, text: "0 of 0 answered", complete: true });
    expect(onboardingProgress({ ...base, answered: 1, total: 3 }).percent).toBe(33);
  });
});
