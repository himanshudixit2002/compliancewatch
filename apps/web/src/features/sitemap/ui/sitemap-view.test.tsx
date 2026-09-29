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
    const ask = container.querySelector("[data-screen='owner.ask']");
    expect(ask?.textContent).toContain("POST /v1/qa/ask");
    expect(ask?.textContent).toContain("KAG track");
    expect(ask?.querySelector("a")).toBeNull();
    expect(container.querySelector("[data-screen='system.health']")?.textContent).toContain(
      "route handler",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  }, 20_000);

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
