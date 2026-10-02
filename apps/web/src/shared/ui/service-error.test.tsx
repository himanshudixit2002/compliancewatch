import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { ServiceError } from "./service-error";

describe("ServiceError", () => {
  it("shows the problem, the status and the correlation id to quote", async () => {
    const { container } = render(
      <ServiceError
        error={{
          message: "Example problem title",
          status: 503,
          requestId: "00000000-0000-4000-8000-000000000001",
          problem: { detail: "Example detail." },
        }}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Example problem title");
    expect(alert.textContent).toContain("HTTP 503");
    expect(alert.textContent).toContain("Example detail.");
    expect(container.querySelector("[data-slot='correlation-id']")?.textContent).toBe(
      "00000000-0000-4000-8000-000000000001",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves out what a failure without a response lacks", () => {
    const { container } = render(
      <ServiceError
        error={{ message: "The service could not be reached.", requestId: "", problem: {} }}
        className="mt-2"
      />,
    );
    expect(container.querySelector("[data-slot='correlation-id']")).toBeNull();
    expect(screen.getByRole("alert").textContent).not.toContain("HTTP");
    expect(screen.getByRole("alert").className).toContain("mt-2");
  });

  it("renders the page's heading above the error when given one", async () => {
    const { container } = render(
      <ServiceError
        heading="Example page"
        error={{ message: "Example problem", status: 500, requestId: "cached:example" }}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example page" })).toBeDefined();
    expect(container.querySelector("[data-slot='service-error-page']")?.className).toContain(
      "max-w-3xl",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
