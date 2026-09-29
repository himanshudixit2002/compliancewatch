import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { BusinessStep } from "./business-step";
import type { BusinessFormResult } from "./business-form";

const PROPS = {
  title: "Add a business",
  consentHref: "/onboarding",
  action: vi.fn(async (): Promise<ActionState<BusinessFormResult>> => ({ status: "idle" })),
  idempotencyInput: <input type="hidden" name="idempotency_key" value="x" />,
  fields: { gstin: "gstin", name: "name", registrationName: "registration_name" },
  againHref: "/onboarding/business",
};

describe("BusinessStep", () => {
  it("shows the second step and the form once the consents are on file", async () => {
    const { container } = render(<BusinessStep {...PROPS} consentAccepted />);
    expect(screen.getByRole("heading", { level: 1, name: "Add a business" })).toBeDefined();
    const steps = screen.getByRole("navigation", { name: "Onboarding steps" });
    expect(steps.querySelector("[aria-current='step']")?.textContent).toContain("Business");
    expect(screen.getByRole("button", { name: "Add the business" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("sends a user without consents back to the consent step", async () => {
    const { container } = render(<BusinessStep {...PROPS} consentAccepted={false} />);
    expect(screen.queryByRole("button", { name: "Add the business" })).toBeNull();
    expect(screen.getByText("Agree to the terms first")).toBeDefined();
    expect(screen.getByRole("link", { name: "Go to the consent step" }).getAttribute("href")).toBe(
      "/onboarding",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
