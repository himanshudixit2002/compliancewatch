import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { businessFromDto, onboardingFromDto, reviewTaskFromDto } from "@/entities/business/mappers";
import { BUSINESS_DTO, ENTITY_ID, ONBOARDING_DTO, REVIEW_TASK_DTO } from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { doneSummaryView } from "../model/onboarding-step";
import { DoneSummary } from "./done-summary";

const VIEW = doneSummaryView({
  business: businessFromDto(BUSINESS_DTO),
  onboarding: onboardingFromDto(ONBOARDING_DTO),
  ontology: ontologyFixture(),
  tasks: [reviewTaskFromDto(REVIEW_TASK_DTO)],
});

const PROPS = {
  title: "Onboarding summary",
  revisitAction: vi.fn(async () => undefined),
  businessIdField: "business_id",
  questionsHref: "/questions",
  businessHref: "/b/example",
};

describe("DoneSummary", () => {
  it("counts the answers, lists what is open and the review tasks, and links on", async () => {
    const { container } = render(<DoneSummary {...PROPS} view={VIEW} />);
    expect(screen.getByRole("heading", { level: 1, name: "Onboarding summary" })).toBeDefined();
    expect(
      screen.getByText(
        "Example business, PAN ABCDE1234F, GSTIN 29ABCDE1234F1Z5. This is what its profile holds now.",
      ),
    ).toBeDefined();
    const steps = screen.getByRole("navigation", { name: "Onboarding steps" });
    expect(steps.querySelector("[aria-current='step']")?.textContent).toContain("Done");
    expect(screen.getByText("Answered").nextElementSibling?.textContent).toBe("3");
    expect(screen.getByRole("heading", { level: 2, name: "Answered Not sure" })).toBeDefined();
    expect(screen.getByText("Example count, on Example business (PAN ABCDE1234F)")).toBeDefined();
    const revisit = screen.getByRole("button", { name: "Answer these now" });
    expect(
      revisit.closest("form")?.querySelector<HTMLInputElement>("input[name='business_id']")?.value,
    ).toBe(ENTITY_ID);
    expect(screen.getByRole("link", { name: "Continue the questions" }).getAttribute("href")).toBe(
      "/questions",
    );
    expect(screen.getByRole("table", { name: "Open review tasks on this business" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Open the business" }).getAttribute("href")).toBe(
      "/b/example",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves out the empty sections", async () => {
    const { container } = render(
      <DoneSummary
        {...PROPS}
        view={{ ...VIEW, unsure: [], missing: [], reviewTasks: [], gstins: [] }}
      />,
    );
    expect(screen.queryByRole("button", { name: "Answer these now" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Continue the questions" })).toBeNull();
    expect(screen.getByText("No review task is open on this business.")).toBeDefined();
    expect(screen.getByText(/GSTIN none yet/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
