import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { EvidenceList } from "../model/evidence";
import { EvidenceView } from "./evidence-view";

const evidence: EvidenceList = {
  obligationName: "GSTR-3B for September",
  dueDate: "2026-10-20",
  items: [
    {
      id: "e1",
      fileName: "challan.pdf",
      sizeBytes: 1536,
      uploadedBy: "Priya Shah",
      uploadedAt: "2026-10-01T09:00:00Z",
      status: "accepted",
    },
    {
      id: "e2",
      fileName: "ack.png",
      sizeBytes: 300,
      uploadedBy: "Ravi Kumar",
      uploadedAt: "2026-10-02T09:00:00Z",
      status: "rejected",
    },
    {
      id: "e3",
      fileName: "return.xlsx",
      sizeBytes: 2 * 1024 * 1024,
      uploadedBy: "Ravi Kumar",
      uploadedAt: "2026-10-02T10:00:00Z",
      status: "submitted",
    },
  ],
};

describe("EvidenceView", () => {
  it("says no evidence is attached yet, without a due date when there is none", async () => {
    const { container } = render(
      <EvidenceView evidence={{ obligationName: "TDS return", dueDate: null, items: [] }} />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Evidence for TDS return" }),
    ).toBeDefined();
    expect(screen.getByText("No evidence yet")).toBeDefined();
    expect(container.textContent).not.toContain("Due ");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("lists each file with its size, uploader, time and status", async () => {
    const { container } = render(<EvidenceView evidence={evidence} />);
    expect(container.textContent).toContain("Due 20 Oct 2026.");
    const accepted = container.querySelector("[data-item='e1']");
    expect(accepted?.textContent).toContain("challan.pdf");
    expect(accepted?.textContent).toContain("1.5 KB");
    expect(accepted?.textContent).toContain("Priya Shah");
    expect(accepted?.querySelector("time")?.getAttribute("datetime")).toBe("2026-10-01T09:00:00Z");
    expect(screen.getByText("Accepted").closest("[data-tone]")?.getAttribute("data-tone")).toBe(
      "success",
    );
    expect(screen.getByText("Rejected").closest("[data-tone]")?.getAttribute("data-tone")).toBe(
      "danger",
    );
    expect(screen.getByText("Submitted").closest("[data-tone]")?.getAttribute("data-tone")).toBe(
      "info",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
