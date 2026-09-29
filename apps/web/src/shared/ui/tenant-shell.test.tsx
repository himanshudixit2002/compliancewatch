import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { usePathname } from "next/navigation";
import { describe, expect, it, vi } from "vitest";
import { TenantShell } from "./tenant-shell";

const items = [
  { id: "system.home", href: "/", label: "Home" },
  { id: "system.sitemap", href: "/sitemap", label: "All screens" },
];

describe("TenantShell", () => {
  it("renders the header links, marks the current one and keeps the skip link and main", async () => {
    vi.mocked(usePathname).mockReturnValue("/sitemap");
    const { container } = render(
      <TenantShell items={items} userMenu={<button type="button">Account</button>}>
        <h1>Body</h1>
      </TenantShell>,
    );
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const current = nav.querySelector("[aria-current='page']");
    expect(current?.textContent).toBe("All screens");
    expect(screen.getByRole("link", { name: "Skip to main content" })).toBeDefined();
    expect(screen.getByRole("main").id).toBe("main");
    expect(screen.getByRole("button", { name: "Account" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
