import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { Breadcrumbs } from "./breadcrumbs";

const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.review", href: "/admin/review", label: "Review queue" },
  { id: "admin.review.task", href: "/admin/review/t1", label: "Review workbench" },
];

describe("Breadcrumbs", () => {
  it("links every ancestor and names the current page without a link", async () => {
    const { container } = render(<Breadcrumbs crumbs={crumbs} />);
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    const links = nav.querySelectorAll("a");
    expect([...links].map((link) => link.getAttribute("href"))).toEqual([
      "/admin",
      "/admin/review",
    ]);
    expect(nav.querySelector("[aria-current='page']")?.textContent).toBe("Review workbench");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders nothing for a single crumb", () => {
    const { container } = render(<Breadcrumbs crumbs={crumbs.slice(0, 1)} />);
    expect(container.innerHTML).toBe("");
  });
});
