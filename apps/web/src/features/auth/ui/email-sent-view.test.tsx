import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { EmailSentView } from "./email-sent-view";

describe("EmailSentView", () => {
  it("says what to do, and shows the link only where nothing was sent", async () => {
    const { container, rerender } = render(<EmailSentView signInHref="/sign-in" />);
    expect(screen.getByRole("heading", { level: 1, name: "Check your email" })).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Use another way to sign in" }).getAttribute("href"),
    ).toBe("/sign-in");
    expect(container.querySelector("[data-slot='dev-email-link']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <EmailSentView
        signInHref="/sign-in"
        devLink="http://localhost:3000/auth/callback?token_hash=x"
      />,
    );
    expect(screen.getByRole("link", { name: "Open the sign-in link" }).getAttribute("href")).toBe(
      "http://localhost:3000/auth/callback?token_hash=x",
    );
    expect(screen.getByText("Development: nothing was sent")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
