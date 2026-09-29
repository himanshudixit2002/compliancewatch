import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { ForbiddenView } from "./forbidden-view";

describe("ForbiddenView", () => {
  it("explains the missing role and links home and to sign-in", async () => {
    const { container } = render(<ForbiddenView />);
    expect(
      screen.getByRole("heading", { level: 1, name: "You cannot open this page" }),
    ).toBeDefined();
    expect(screen.getByRole("link", { name: "Go to the home page" }).getAttribute("href")).toBe(
      "/",
    );
    expect(
      screen.getByRole("link", { name: "Sign in with another account" }).getAttribute("href"),
    ).toBe("/sign-in");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
