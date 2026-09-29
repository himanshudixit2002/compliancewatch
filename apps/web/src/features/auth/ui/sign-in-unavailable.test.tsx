import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { SignInUnavailable } from "./sign-in-unavailable";

describe("SignInUnavailable", () => {
  it("shows the problem under the sign-in heading", async () => {
    const { container } = render(
      <SignInUnavailable
        title="Sign-in is not configured"
        detail="Set CW_WEB_AUTH_PROVIDER to fake (local and test only) or supabase."
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeDefined();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Sign-in is not configured");
    expect(alert.textContent).toContain("CW_WEB_AUTH_PROVIDER");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
