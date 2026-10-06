import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { usageFromDto } from "@/entities/llm/mappers";
import { EXAMPLE_TENANT_ID, usageDto } from "@/test/llm-fixture";
import { readUsage, usageRow } from "../model/usage";
import { UsageView } from "./usage-view";

const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.llm.usage", href: "/admin/llm/usage", label: "Usage and budgets" },
];

const NOW = new Date("2000-01-15T00:00:00Z");

describe("UsageView", () => {
  it("shows each budget with its spend, share, alarm and reset", async () => {
    const { container } = render(
      <UsageView
        title="Usage and budgets"
        crumbs={crumbs}
        pageHref="/admin/llm/usage"
        read={readUsage({}, NOW)}
        view={{
          month: "2000-01",
          monthLabel: "January 2000",
          overview: true,
          rows: [
            usageRow(usageFromDto(usageDto())),
            usageRow(usageFromDto(usageDto({ key: "smoke", alarmed: true, ratio: "0.900000" }))),
          ],
        }}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "Every feature's budget for January 2000" }),
    ).toBeDefined();
    const qa = container.querySelector("[data-usage='feature:qa']");
    expect(qa?.textContent).toContain("Rs 1,234.0012");
    expect(qa?.textContent).toContain("Within the alarm line");
    expect(container.querySelector("[data-usage='feature:smoke']")?.textContent).toContain(
      "Alarm raised",
    );
    expect(screen.getAllByRole("progressbar")[0]?.getAttribute("aria-valuetext")).toBe(
      "6.17% of Rs 20,000.00",
    );
    expect((screen.getByLabelText(/^Month/) as HTMLInputElement).value).toBe("2000-01");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows one tenant's budget under its id, with the question kept in the form", async () => {
    const { container } = render(
      <UsageView
        title="Usage and budgets"
        crumbs={crumbs}
        pageHref="/admin/llm/usage"
        read={readUsage({ tenant: EXAMPLE_TENANT_ID, feature: "qa", month: "2000-01" }, NOW)}
        view={{
          month: "2000-01",
          monthLabel: "January 2000",
          overview: false,
          rows: [
            usageRow(
              usageFromDto(usageDto({ scope: "tenant", key: EXAMPLE_TENANT_ID, alarmed: true })),
            ),
          ],
        }}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "Budget for January 2000" }),
    ).toBeDefined();
    const card = container.querySelector(`[data-usage='tenant:${EXAMPLE_TENANT_ID}']`);
    expect(card?.textContent).toContain(`Tenant: ${EXAMPLE_TENANT_ID}`);
    expect(card?.textContent).toContain("Alarm raised");
    expect((screen.getByLabelText(/^Tenant id/) as HTMLInputElement).value).toBe(EXAMPLE_TENANT_ID);
    expect((screen.getByLabelText(/^Feature/) as HTMLSelectElement).value).toBe("qa");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks the fields it cannot use and shows a failed read", async () => {
    const { container } = render(
      <UsageView
        title="Usage and budgets"
        crumbs={crumbs}
        pageHref="/admin/llm/usage"
        read={readUsage({ tenant: "x", month: "2000-13" }, NOW)}
        view={null}
        error={{ message: "Example outage", status: 503, requestId: "req-example-6" }}
      />,
    );
    expect(screen.getByText("This is not a tenant id (a UUID).")).toBeDefined();
    expect(screen.getByText("Give the month as YYYY-MM, such as 2000-01.")).toBeDefined();
    expect((screen.getByLabelText(/^Tenant id/) as HTMLInputElement).value).toBe("x");
    expect(screen.getByText("Example outage")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
