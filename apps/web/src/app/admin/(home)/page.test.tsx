import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { getAdminHome } from "@/features/admin-home/queries";
import { requireScreenSession } from "@/server/dal";
import AdminHomePage, { metadata } from "./page";

vi.mock("@/server/dal", () => ({ requireScreenSession: vi.fn() }));
vi.mock("@/features/admin-home/queries", () => ({ getAdminHome: vi.fn() }));

const analyst = {
  userId: "user-1",
  tenantId: "internal",
  tenantKind: "internal" as const,
  roles: ["analyst" as const],
};

describe("AdminHomePage", () => {
  it("runs the screen's gate, then renders the counts, the services and the tool list", async () => {
    vi.mocked(requireScreenSession).mockResolvedValue(analyst as never);
    vi.mocked(getAdminHome).mockResolvedValue({
      tiles: [
        {
          key: "rules",
          title: "Rules",
          value: "3",
          detail: null,
          href: null,
          error: null,
        },
      ],
      services: { up: 10, total: 10, down: [], systemHref: null },
    });
    render(await AdminHomePage());
    expect(vi.mocked(requireScreenSession).mock.calls[0]?.[0].id).toBe("admin.home");
    expect(vi.mocked(getAdminHome)).toHaveBeenCalledWith(analyst);
    expect(screen.getByRole("heading", { level: 1, name: "Internal tools" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 3, name: "Rules" })).toBeDefined();
    expect(screen.getByText("All 10 services answer their health check.")).toBeDefined();
    expect(screen.getByRole("link", { name: "Review queue" })).toBeDefined();
    expect(metadata.title).toBe("Internal tools");
  });
});
