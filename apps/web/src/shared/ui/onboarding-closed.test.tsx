import { render, screen } from "@testing-library/react";
import { DRAFT_BANNER_TEXT } from "@compliancewatch/ui";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { OnboardingClosed } from "./onboarding-closed";

describe("OnboardingClosed", () => {
  it("keeps the step's heading, offers no form and links each draft with its version", async () => {
    const { container } = render(
      <OnboardingClosed
        title="Example step"
        step="business"
        documents={[
          { name: "example-notice", title: "Example notice", version: "9.9-draft" },
          { name: "example-terms", title: "Example terms", version: "9.8-draft" },
        ]}
        documentHref={(name) => `/legal/${name}`}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example step" })).toBeDefined();
    expect(
      screen.getByText("Onboarding is closed until the legal documents are reviewed."),
    ).toBeDefined();
    expect(screen.getByText(DRAFT_BANNER_TEXT)).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Example notice, version 9.9-draft" }).getAttribute("href"),
    ).toBe("/legal/example-notice");
    expect(screen.getByRole("link", { name: "Example terms, version 9.8-draft" })).toBeDefined();
    expect(container.querySelector("form")).toBeNull();
    expect(
      screen
        .getByRole("navigation", { name: "Onboarding steps" })
        .querySelector("[aria-current='step']")?.textContent,
    ).toContain("Business");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
