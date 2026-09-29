import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { planFromDto } from "@/entities/billing/mappers";
import { PLAN_DTOS } from "@/test/billing-fixture";
import { planView } from "../model/plans";
import { BillingView } from "./billing-view";

describe("BillingView", () => {
  it("lists the plans as the service states them, then the subscribe form", async () => {
    const { container } = render(
      <BillingView
        title="Billing"
        plans={PLAN_DTOS.map(planFromDto).map(planView)}
        crumbs={[
          { id: "owner.settings", href: "/settings", label: "Settings" },
          { id: "owner.settings.billing", href: "/settings/billing", label: "Billing" },
        ]}
        tabs={[]}
        action={vi.fn(async () => ({ status: "idle" as const }))}
        fields={{ plan: "plan_key", email: "email", name: "name" }}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Billing" })).toBeDefined();
    const monthly = container.querySelector("[data-plan='example_monthly']") as HTMLElement;
    expect(monthly.textContent).toContain("Rs 1,499.00");
    expect(monthly.textContent).toContain("per month");
    expect(monthly.textContent).toContain("Example description.");
    const yearly = container.querySelector("[data-plan='example_yearly']") as HTMLElement;
    expect(yearly.querySelectorAll("p")).toHaveLength(2);
    expect(screen.getByRole("form", { name: "Start a subscription" })).toBeDefined();
    expect(
      await runAxe(container.querySelector("[data-slot='plans']") as Element),
    ).toHaveNoViolations();
  });
});
