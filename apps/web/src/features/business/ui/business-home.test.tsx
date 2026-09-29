import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { businessFromDto, onboardingFromDto, reviewTaskFromDto } from "@/entities/business/mappers";
import { BUSINESS_DTO, ONBOARDING_DTO, REVIEW_TASK_DTO } from "@/test/business-fixture";
import { businessHomeView } from "../model/business-pages";
import { BusinessHome, type BusinessHomeLinks } from "./business-home";

const VIEW = businessHomeView(businessFromDto(BUSINESS_DTO), onboardingFromDto(ONBOARDING_DTO), [
  reviewTaskFromDto(REVIEW_TASK_DTO),
]);
const HEADER = {
  crumbs: [
    { id: "owner.businesses", href: "/businesses", label: "Businesses" },
    { id: "owner.business", href: "/b/x", label: "Example business" },
  ],
  tabs: [
    { id: "owner.business", href: "/b/x", label: "Business" },
    { id: "owner.business.profile", href: "/b/x/profile", label: "Profile" },
  ],
};
const LINKS: BusinessHomeLinks = {
  profile: "/b/x/profile",
  attributes: "/b/x/attributes",
  snapshot: "/b/x/snapshot",
  reviewTasks: "/b/x/review-tasks",
  questions: "/onboarding/x/questions",
  done: "/onboarding/x/done",
};

describe("BusinessHome", () => {
  it("names the business with its registrations, onboarding progress, tiles and later screens", async () => {
    const { container } = render(
      <BusinessHome
        view={VIEW}
        header={HEADER}
        links={LINKS}
        later={[{ id: "owner.changes", title: "Changes", status: "waiting", href: "/b/x/changes" }]}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example business" })).toBeDefined();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeDefined();
    expect(screen.getByRole("navigation", { name: "Pages of this business" })).toBeDefined();
    expect(screen.getByText("29ABCDE1234F1Z5 (Example registration)")).toBeDefined();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuetext")).toBe("4 of 8 answered");
    expect(screen.getByRole("link", { name: "Continue the questions" }).getAttribute("href")).toBe(
      LINKS.questions,
    );
    expect(screen.getByText("3 answered, 1 not sure, 1 does not apply.")).toBeDefined();
    expect(screen.getByText("1 open.")).toBeDefined();
    expect(screen.getByRole("link", { name: "Changes" }).getAttribute("href")).toBe("/b/x/changes");
    expect(screen.getByText("Waiting for a backend")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("points at the summary once complete and leaves onboarding links out for a reader", () => {
    const complete = { ...VIEW, progress: { ...VIEW.progress, complete: true } };
    const { rerender } = render(
      <BusinessHome view={complete} header={HEADER} links={LINKS} later={[]} />,
    );
    expect(screen.getByText("Every onboarding question has an answer.")).toBeDefined();
    expect(
      screen.getByRole("link", { name: "See the onboarding summary" }).getAttribute("href"),
    ).toBe(LINKS.done);
    expect(screen.queryByRole("heading", { name: "Not available yet" })).toBeNull();
    rerender(
      <BusinessHome
        view={{ ...VIEW, header: { ...VIEW.header, registrations: [] } }}
        header={HEADER}
        links={{ ...LINKS, questions: null, done: null }}
        later={[]}
      />,
    );
    expect(screen.queryByRole("link", { name: "Continue the questions" })).toBeNull();
    expect(screen.getByText("No GSTIN registration yet")).toBeDefined();
  });
});
