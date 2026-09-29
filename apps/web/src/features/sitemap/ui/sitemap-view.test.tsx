import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { sitemapSections } from "../model/rows";
import { AwaitedList, SitemapView } from "./sitemap-view";

describe("SitemapView", () => {
  it("renders one captioned table per section with links, chips and awaited routes", async () => {
    const { container } = render(<SitemapView sections={sitemapSections()} />);
    expect(screen.getByRole("heading", { level: 1, name: "All screens" })).toBeDefined();
    const tables = screen.getAllByRole("table");
    expect(tables.length).toBe(5);
    expect(within(tables[0] as HTMLElement).getByText("Your business")).toBeDefined();
    expect(screen.getByRole("link", { name: "Review queue" }).getAttribute("href")).toBe(
      "/admin/review",
    );
    expect(screen.getByRole("link", { name: "Terms of service" }).getAttribute("href")).toBe(
      "/legal/terms-of-service",
    );
    const stats = container.querySelector("[data-screen='admin.review.stats']");
    expect(stats?.textContent).toContain("GET /v1/rulebook/review/stats");
    expect(stats?.textContent).toContain("KAG track");
    expect(stats?.querySelector("a")?.getAttribute("href")).toBe("/admin/review/stats");
    const obligation = container.querySelector("[data-screen='owner.obligation']");
    expect(obligation?.querySelector("a")).toBeNull();
    expect(container.querySelector("[data-screen='system.health']")?.textContent).toContain(
      "route handler",
    );
    // axe over every registry row is page sized and slow in jsdom on CI runners, so it checks one
    // section's table here; e2e/sitemap.spec.ts runs AxeBuilder over the whole /sitemap page.
    const system = container.querySelector<HTMLElement>("[data-section='system']");
    expect(system).not.toBeNull();
    expect(await runAxe(system as HTMLElement)).toHaveNoViolations();
  });

  it("shows the first three awaited routes and counts the rest", () => {
    const items = Array.from({ length: 5 }, (_, i) => ({
      method: "GET",
      path: `/v1/x/${i}`,
      owner: "services track",
    }));
    render(<AwaitedList items={items} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText("+2 more")).toBeDefined();
  });

  it("says none when nothing is awaited", () => {
    render(<AwaitedList items={[]} />);
    expect(screen.getByText("None")).toBeDefined();
  });
});
