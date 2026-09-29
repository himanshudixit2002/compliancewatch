import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AdminHomePage, { metadata } from "./page";

describe("AdminHomePage", () => {
  it("renders the registry-driven tool list under the registry title", () => {
    render(<AdminHomePage />);
    expect(screen.getByRole("heading", { level: 1, name: "Internal tools" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Review queue" })).toBeDefined();
    expect(metadata.title).toBe("Internal tools");
  });
});
