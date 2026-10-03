import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { EvidenceRow } from "./evidence-rows";
import { EvidenceTable } from "./evidence-table";

function row(overrides: Partial<EvidenceRow>): EvidenceRow {
  return {
    id: "e1",
    fileName: "challan.pdf",
    size: "1.5 KB",
    uploadedBy: "Priya Shah",
    uploadedAt: "2026-10-01T09:00:00Z",
    uploadedLabel: "1 Oct 2026, 2:30 pm IST",
    status: "accepted",
    statusLabel: "Accepted",
    statusTone: "success",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "e1" }),
  row({
    id: "e2",
    fileName: "return.xlsx",
    status: "submitted",
    statusLabel: "Submitted",
    statusTone: "info",
  }),
];

const TABS = [
  { value: "submitted", label: "Submitted" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
];

function shownIds(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-item]")].map(
    (item) => item.getAttribute("data-item") ?? "",
  );
}

describe("EvidenceTable", () => {
  it("opens on all files and shows each file's details", async () => {
    const { container } = render(<EvidenceTable rows={ROWS} statusTabs={TABS} />);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "All files",
      "Submitted",
      "Accepted",
      "Rejected",
    ]);
    expect(screen.getByRole("tab", { name: "All files" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(shownIds(container)).toEqual(["e1", "e2"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 2 of 2 files.");
    expect(screen.getByRole("table", { name: "Evidence files" })).toBeDefined();
    const first = container.querySelector("[data-item='e1']") as HTMLElement;
    expect(first.textContent).toContain("challan.pdf");
    expect(first.textContent).toContain("1.5 KB");
    expect(first.textContent).toContain("Priya Shah");
    const time = first.querySelector("time");
    expect(time?.getAttribute("datetime")).toBe("2026-10-01T09:00:00Z");
    expect(time?.textContent).toBe("1 Oct 2026, 2:30 pm IST");
    const chip = first.querySelector("[data-slot='status-chip']");
    expect(chip?.textContent).toBe("Accepted");
    expect(chip?.getAttribute("data-tone")).toBe("success");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("narrows to a review status and says when no file has it", async () => {
    const user = userEvent.setup();
    const { container } = render(<EvidenceTable rows={ROWS} statusTabs={TABS} />);

    await user.click(screen.getByRole("tab", { name: "Submitted" }));
    expect(shownIds(container)).toEqual(["e2"]);
    expect(screen.getByRole("status").textContent).toBe("Showing 1 of 2 files.");

    await user.click(screen.getByRole("tab", { name: "Rejected" }));
    expect(shownIds(container)).toEqual([]);
    expect(screen.getByRole("heading", { level: 2, name: "No files match" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("tab", { name: "All files" }));
    expect(shownIds(container)).toEqual(["e1", "e2"]);
  });
});
