import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { SessionMenu } from "./session-menu";
import { SignOutButton } from "./sign-out-button";

describe("SessionMenu", () => {
  it("links the name to the account page and offers sign out", async () => {
    const { container } = render(<SessionMenu session={{ displayName: "Example owner" }} />);
    const nav = screen.getByRole("navigation", { name: "Account" });
    expect(screen.getByRole("link", { name: "Example owner" }).getAttribute("href")).toBe(
      "/account",
    );
    expect(nav.querySelector("form[data-slot='sign-out']")?.getAttribute("action")).toBe(
      "/sign-out",
    );
    expect(screen.getByRole("button", { name: "Sign out" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe("SignOutButton", () => {
  it("is a POST form to the sign-out handler", () => {
    const { container } = render(<SignOutButton />);
    const form = container.querySelector("form");
    expect(form?.getAttribute("method")).toBe("post");
    expect(form?.getAttribute("action")).toBe("/sign-out");
    expect(screen.getByRole("button", { name: "Sign out" }).getAttribute("type")).toBe("submit");
  });
});
