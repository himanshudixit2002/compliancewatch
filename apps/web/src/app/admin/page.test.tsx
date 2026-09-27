import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AdminHomePage from "./page";

describe("AdminHomePage", () => {
  it("renders the admin placeholder", () => {
    render(<AdminHomePage />);
    expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeDefined();
  });
});
