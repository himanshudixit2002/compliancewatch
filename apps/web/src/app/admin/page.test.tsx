import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { requireAdmin } from "@/server/dal";
import AdminHomePage, { metadata } from "./page";

vi.mock("@/server/dal", () => ({ requireAdmin: vi.fn() }));

describe("AdminHomePage", () => {
  it("runs the admin gate, then renders the registry-driven tool list under the registry title", async () => {
    render(await AdminHomePage());
    expect(vi.mocked(requireAdmin)).toHaveBeenCalledWith({ next: "/admin" });
    expect(screen.getByRole("heading", { level: 1, name: "Internal tools" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Review queue" })).toBeDefined();
    expect(metadata.title).toBe("Internal tools");
  });
});
