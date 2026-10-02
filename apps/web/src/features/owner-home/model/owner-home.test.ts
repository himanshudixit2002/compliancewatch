import { describe, expect, it } from "vitest";
import { emptyOwnerHome, hasBusinesses, onboardingOpen } from "./owner-home";

describe("hasBusinesses", () => {
  it("is true once the owner has a business", () => {
    expect(hasBusinesses(emptyOwnerHome())).toBe(false);
    expect(hasBusinesses({ ...emptyOwnerHome(), businessesCount: 1 })).toBe(true);
  });
});

describe("onboardingOpen", () => {
  it("is true only while questions remain unanswered", () => {
    expect(onboardingOpen(emptyOwnerHome())).toBe(false);
    const onboarding = { businessName: "Acme", answered: 4, total: 17 };
    expect(onboardingOpen({ ...emptyOwnerHome(), onboarding })).toBe(true);
    expect(
      onboardingOpen({ ...emptyOwnerHome(), onboarding: { ...onboarding, answered: 17 } }),
    ).toBe(false);
  });
});
