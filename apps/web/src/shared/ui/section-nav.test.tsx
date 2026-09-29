import { render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { SectionNav } from "./section-nav";

const ITEMS = [
  { id: "a", href: "/b/x", label: "Example home" },
  { id: "b", href: "/b/x/profile", label: "Example profile" },
];

describe("SectionNav", () => {
  it("marks the longest link that holds the current path", async () => {
    vi.mocked(usePathname).mockReturnValue("/b/x/profile");
    const { container } = render(<SectionNav items={ITEMS} label="Example pages" />);
    const nav = screen.getByRole("navigation", { name: "Example pages" });
    expect(nav.querySelector("[aria-current='page']")?.textContent).toBe("Example profile");
    expect(
      screen.getByRole("link", { name: "Example home" }).getAttribute("aria-current"),
    ).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks the home link on its own path and renders nothing for one link", () => {
    vi.mocked(usePathname).mockReturnValue("/b/x");
    const { container, rerender } = render(<SectionNav items={ITEMS} label="Example pages" />);
    expect(container.querySelector("[aria-current='page']")?.textContent).toBe("Example home");
    rerender(<SectionNav items={ITEMS.slice(0, 1)} label="Example pages" />);
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
