import type { Route } from "next";
import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { emptyOwnerHome, type OwnerHomeSummary } from "../model/owner-home";
import { OwnerHomeView, type OwnerHomeLinks } from "./owner-home-view";

const links: OwnerHomeLinks = {
  businesses: "/businesses" as Route,
  addBusiness: "/onboarding" as Route,
};

const withBusinesses: OwnerHomeSummary = {
  businessesCount: 2,
  pendingReview: 3,
  openObligations: 7,
  upcomingDeadlines: 4,
  recentChanges: 1,
  onboarding: null,
};

function href(name: string): string | null {
  return screen.getByRole("link", { name }).getAttribute("href");
}

describe("OwnerHomeView", () => {
  it("invites adding the first business when there is none, without the stats", async () => {
    const { container } = render(<OwnerHomeView summary={emptyOwnerHome()} links={links} />);
    expect(screen.getByRole("heading", { level: 1, name: "Home" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Welcome to ComplianceWatch" })).toBeDefined();
    expect(href("Add your first business")).toBe("/onboarding");
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the counts and business links once there are businesses", async () => {
    const { container } = render(<OwnerHomeView summary={withBusinesses} links={links} />);
    expect(screen.queryByText("Welcome to ComplianceWatch")).toBeNull();
    expect(container.querySelectorAll("[data-slot='stat-card']")).toHaveLength(4);
    expect(screen.getByText("7")).toBeDefined();
    expect(href("Your businesses (2)")).toBe("/businesses");
    expect(href("Add a business")).toBe("/onboarding");
    expect(screen.queryByRole("link", { name: "View pending review" })).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("links each stat that has a target and shows open onboarding", async () => {
    const { container } = render(
      <OwnerHomeView
        summary={{
          ...withBusinesses,
          onboarding: { businessName: "Acme Traders", answered: 4, total: 17 },
        }}
        links={{
          ...links,
          onboarding: "/onboarding/questions" as Route,
          pendingReview: "/review" as Route,
          openObligations: "/obligations" as Route,
          upcomingDeadlines: "/deadlines" as Route,
          recentChanges: "/changes" as Route,
        }}
      />,
    );
    expect(href("View pending review")).toBe("/review");
    expect(href("View open obligations")).toBe("/obligations");
    expect(href("View upcoming deadlines")).toBe("/deadlines");
    expect(href("View recent changes")).toBe("/changes");
    expect(screen.getByRole("heading", { name: "Finish setting up Acme Traders" })).toBeDefined();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuetext")).toBe("4 of 17 answered");
    expect(href("Continue onboarding")).toBe("/onboarding/questions");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("continues onboarding through the add-business link when no onboarding link is given", () => {
    render(
      <OwnerHomeView
        summary={{
          ...withBusinesses,
          onboarding: { businessName: "Acme Traders", answered: 0, total: 5 },
        }}
        links={links}
      />,
    );
    expect(href("Continue onboarding")).toBe("/onboarding");
  });
});
