import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { homeLinks } from "../model/links";
import { HomeView } from "./home-view";

describe("HomeView", () => {
  it("shows the landing with a sign-in link and the legal drafts to an anonymous visitor", async () => {
    const { container } = render(<HomeView links={homeLinks()} sections={null} />);
    expect(screen.getByRole("heading", { level: 1, name: "ComplianceWatch" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe("/sign-in");
    expect(screen.getByRole("link", { name: "Privacy notice" }).getAttribute("href")).toBe(
      "/legal/privacy-notice",
    );
    expect(screen.getByRole("link", { name: "Every screen and its status" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("lists the sections a session may open with a status chip each", async () => {
    const sections = [
      {
        key: "business",
        label: "Your business",
        items: [
          {
            id: "owner.obligations",
            title: "Obligations",
            href: "/b/1/obligations",
            status: "waiting" as const,
          },
        ],
      },
    ];
    const { container } = render(<HomeView links={homeLinks()} sections={sections} />);
    expect(screen.getByRole("heading", { level: 1, name: "Home" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Obligations" }).getAttribute("href")).toBe(
      "/b/1/obligations",
    );
    expect(screen.getByText("Waiting for a backend")).toBeDefined();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
