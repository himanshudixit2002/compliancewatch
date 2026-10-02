import { render, screen } from "@testing-library/react";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { RiskItem } from "../model/risk";
import { RiskView } from "./risk-view";

const hrefFor = (id: string) => `/b/biz_1/risk/${id}` as Route;

const RISKS: RiskItem[] = [
  {
    id: "risk_1",
    title: "Late GST filing",
    description: "Penalty and interest.",
    severity: "high",
    status: "active",
    likelihood: 40.4,
    identifiedAt: "2026-04-10",
    owner: "Asha",
  },
  {
    id: "risk_2",
    title: "Missing consent",
    description: "Marketing without consent.",
    severity: "low",
    status: "mitigated",
    likelihood: 10,
    identifiedAt: "2026-03-01T10:00:00Z",
    owner: "Ravi",
  },
];

function figure(container: HTMLElement, label: string): string | null | undefined {
  const term = [...container.querySelectorAll("dt")].find((dt) => dt.textContent === label);
  return term?.nextElementSibling?.textContent;
}

describe("RiskView", () => {
  it("summarises the register and lists the risks, worded and linked", async () => {
    const { container } = render(<RiskView risks={RISKS} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 1, name: "Risk register" })).toBeDefined();
    expect(figure(container, "Total risks")).toBe("2");
    expect(figure(container, "High severity")).toBe("1");
    expect(figure(container, "Medium severity")).toBe("0");
    expect(figure(container, "Mitigated")).toBe("1");
    const first = container.querySelector("[data-risk='risk_1']") as HTMLElement;
    expect(first.textContent).toContain("High");
    expect(first.textContent).toContain("Active");
    expect(first.textContent).toContain("40%");
    expect(first.textContent).toContain("10 Apr 2026");
    const second = container.querySelector("[data-risk='risk_2']") as HTMLElement;
    expect(second.textContent).toContain("1 Mar 2026");
    expect(screen.getByRole("link", { name: "Missing consent" }).getAttribute("href")).toBe(
      "/b/biz_1/risk/risk_2",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the empty state when no risk is recorded", async () => {
    const { container } = render(<RiskView risks={[]} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { name: "No risks recorded" })).toBeDefined();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
