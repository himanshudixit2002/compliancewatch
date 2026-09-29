import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HomePage, { metadata } from "./page";

describe("HomePage", () => {
  it("renders the landing with its sign-in link and takes its title from the registry", () => {
    render(<HomePage />);
    expect(screen.getByRole("heading", { level: 1, name: "ComplianceWatch" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe("/sign-in");
    expect(metadata.title).toBe("Home");
  });
});
