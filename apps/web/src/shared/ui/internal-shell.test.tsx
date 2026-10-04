import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { usePathname } from "next/navigation";
import { describe, expect, it, vi } from "vitest";
import { InternalShell } from "./internal-shell";

const groups = [
  {
    key: "review",
    label: "Review",
    items: [
      {
        id: "admin.review",
        href: "/admin/review",
        label: "Review queue",
        status: "waiting" as const,
      },
      { id: "admin.review.stats", href: "/admin/review/stats", label: "Review stats" },
    ],
  },
];

describe("InternalShell", () => {
  it("renders the grouped tools with the active link and the environment banner", async () => {
    vi.mocked(usePathname).mockReturnValue("/admin/review/stats");
    const { container } = render(
      <InternalShell groups={groups} environment="local">
        <h1>Body</h1>
      </InternalShell>,
    );
    expect(screen.getByRole("status").textContent).toContain("local");
    const sidebar = container.querySelector("aside");
    const current = sidebar?.querySelector("[aria-current='page']");
    expect(current?.textContent).toBe("Review stats");
    expect(sidebar?.querySelectorAll("[aria-current=page]")).toHaveLength(1);
    expect(sidebar?.textContent).toContain("Review");
    const waiting = screen.getAllByRole("link", { name: "Review queue" })[0];
    const hint = container.querySelector(`[id="${waiting?.getAttribute("aria-describedby")}"]`);
    expect(hint?.textContent).toBe("Waiting");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
