import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { KeysetPager } from "./keyset-pager";

const labels = { label: "Example pages", nextLabel: "Next page", firstLabel: "First page" };

describe("KeysetPager", () => {
  it("links the next page and the first one in a named navigation", async () => {
    const { container } = render(
      <KeysetPager {...labels} nextHref="/example?after=2" firstHref="/example" />,
    );
    const nav = screen.getByRole("navigation", { name: "Example pages" });
    expect(
      [...nav.querySelectorAll("a")].map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["First page", "/example"],
      ["Next page", "/example?after=2"],
    ]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers only the way that exists", () => {
    render(<KeysetPager {...labels} nextHref="/example?after=2" firstHref={null} />);
    expect(screen.queryByRole("link", { name: "First page" })).toBeNull();
    expect(screen.getByRole("link", { name: "Next page" })).toBeDefined();
  });

  it("renders nothing for a list that fits on one page", () => {
    const { container } = render(<KeysetPager {...labels} nextHref={null} firstHref={null} />);
    expect(container.innerHTML).toBe("");
  });
});
