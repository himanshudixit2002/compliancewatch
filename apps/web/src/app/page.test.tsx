import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HomePage from "./page";

describe("HomePage", () => {
  it("renders the product heading and links to the internal tools", () => {
    render(<HomePage />);
    expect(screen.getByRole("heading", { level: 1, name: "ComplianceWatch" })).toBeDefined();
    expect(screen.getByRole("link", { name: /\/admin/ }).getAttribute("href")).toBe("/admin");
  });
});
