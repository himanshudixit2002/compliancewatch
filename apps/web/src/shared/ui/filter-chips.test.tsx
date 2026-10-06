import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { FilterChips } from "./filter-chips";

describe("FilterChips", () => {
  it("links each way of showing the list and marks the current one", async () => {
    const { container } = render(
      <FilterChips
        label="Show examples by state"
        chips={[
          { key: "open", label: "Open", href: "/example", current: true },
          { key: "closed", label: "Closed", href: "/example?state=closed", current: false },
        ]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Show examples by state" });
    expect(nav.querySelector("[aria-current='true']")?.textContent).toBe("Open");
    expect(screen.getByRole("link", { name: "Closed" }).getAttribute("href")).toBe(
      "/example?state=closed",
    );
    expect(screen.getByRole("link", { name: "Closed" }).getAttribute("aria-current")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
