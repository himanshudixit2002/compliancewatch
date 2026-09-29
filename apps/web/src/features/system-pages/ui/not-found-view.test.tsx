import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { NotFoundView } from "./not-found-view";

describe("NotFoundView", () => {
  it("says the page is missing and links home", async () => {
    const { container } = render(<NotFoundView />);
    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Go to the home page" }).getAttribute("href")).toBe(
      "/",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
