import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Button } from "./button";
import { ErrorState } from "./error-state";

describe("ErrorState", () => {
  it("is an alert with the title, detail, status, correlation id and retry link", async () => {
    const { container } = render(
      <ErrorState
        title="Profile service unavailable"
        detail="Try again in a minute."
        status={503}
        correlationId="req-0000"
        retryHref="/profile"
        action={<Button variant="ghost">Report</Button>}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert.dataset.status).toBe("503");
    expect(alert.textContent).toContain("Profile service unavailable");
    expect(alert.textContent).toContain("Try again in a minute.");
    expect(alert.textContent).toContain("HTTP 503");
    expect(screen.getByText("req-0000").tagName).toBe("CODE");
    expect(screen.getByRole("button", { name: "Copy correlation id" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Try again" }).getAttribute("href")).toBe("/profile");
    expect(screen.getByRole("button", { name: "Report" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders the minimum without id, status or actions", () => {
    const { container } = render(<ErrorState title="Failed" />);
    expect(container.querySelector('[data-slot="correlation-id"]')).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByRole("alert").textContent).not.toContain("HTTP");
  });
});
