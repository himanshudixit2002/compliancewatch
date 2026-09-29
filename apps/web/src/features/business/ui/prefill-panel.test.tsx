import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { PrefillPanel, type PrefillPanelResult } from "./prefill-panel";

const LOOKED_UP: PrefillPanelResult = {
  businessName: "Example business",
  pan: "ABCDE1234F",
  gstin: "29ABCDE1234F1Z5",
  created: true,
  lookedUp: true,
  rows: [
    { key: "legalName", label: "Legal name", value: "Example Legal Name Limited" },
    { key: "stateCode", label: "State", value: "01 (Example place one)" },
  ],
  applied: ["Registration type", "State codes"],
  reviewTaskId: null,
  progressText: "5 of 17 answered",
};

describe("PrefillPanel", () => {
  it("lists what the lookup returned and what it stored", async () => {
    const { container } = render(<PrefillPanel result={LOOKED_UP} />);
    expect(
      screen.getByRole("heading", { level: 2, name: "Example business is added" }),
    ).toBeDefined();
    expect(screen.getByText("ABCDE1234F")).toBeDefined();
    expect(screen.getByText("5 of 17 answered")).toBeDefined();
    expect(
      screen.getByRole("heading", { level: 3, name: "What the GSTIN lookup returned" }),
    ).toBeDefined();
    expect(screen.getByText("Example Legal Name Limited")).toBeDefined();
    expect(screen.getByText("01 (Example place one)")).toBeDefined();
    expect(
      screen.getByText("Stored on the profile from the GSTIN: Registration type, State codes."),
    ).toBeDefined();
    expect(container.querySelector("[data-slot='prefill-manual']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when the lookup stored nothing new", () => {
    render(<PrefillPanel result={{ ...LOOKED_UP, created: false, applied: [] }} />);
    expect(
      screen.getByRole("heading", { name: "Example business was already in your account" }),
    ).toBeDefined();
    expect(screen.getByText(/Nothing new was stored/)).toBeDefined();
  });

  it("says plainly that nothing was looked up, with the review task", async () => {
    const { container } = render(
      <PrefillPanel
        result={{
          ...LOOKED_UP,
          lookedUp: false,
          rows: [],
          applied: ["State codes"],
          reviewTaskId: "00000000-0000-4000-8000-0000000000f1",
        }}
      />,
    );
    const manual = container.querySelector("[data-slot='prefill-manual']");
    expect(manual?.textContent).toContain("No lookup details for this GSTIN");
    expect(manual?.textContent).toContain("00000000-0000-4000-8000-0000000000f1");
    expect(manual?.textContent).toContain("Stored on the profile from the GSTIN: State codes.");
    expect(screen.queryByText("What the GSTIN lookup returned")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("leaves out the task line when the service opened none", () => {
    const { container } = render(
      <PrefillPanel result={{ ...LOOKED_UP, lookedUp: false, rows: [], applied: [] }} />,
    );
    expect(container.querySelector("[data-slot='prefill-manual']")?.textContent).not.toContain(
      "review task was opened",
    );
  });
});
