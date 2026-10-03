import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { EVIDENCE_UPLOAD_FIELDS, type EvidenceList } from "../model/evidence";
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

function figures(container: HTMLElement): Record<string, { value: string; tone: string }> {
  const cards = [...container.querySelectorAll<HTMLElement>("[data-slot='stat-card']")];
  return Object.fromEntries(
    cards.map((card) => [
      card.querySelector("dt")?.textContent ?? "",
      {
        value: card.querySelector("dd")?.textContent ?? "",
        tone: card.getAttribute("data-tone") ?? "",
      },
    ]),
  );
}

describe("EvidenceView", () => {
  it("says no evidence is attached yet, without a due date or an upload form", async () => {
    const { container } = render(
      <EvidenceView evidence={{ obligationName: "TDS return", dueDate: null, items: [] }} />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Evidence for TDS return" }),
    ).toBeDefined();
    expect(screen.getByText("Files attached as proof this obligation was met.")).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "No evidence yet" })).toBeDefined();
    expect(container.textContent).not.toContain("Due ");
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(container.querySelector("form")).toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("counts the files by review and lists each with its size, uploader, time and status", async () => {
    const { container } = render(<EvidenceView evidence={evidence} />);
    expect(container.textContent).toContain("Due 20 Oct 2026.");
    expect(figures(container)).toEqual({
      "Total files": { value: "3", tone: "neutral" },
      "Awaiting review": { value: "1", tone: "info" },
      Accepted: { value: "1", tone: "success" },
      Rejected: { value: "1", tone: "danger" },
    });
    const accepted = container.querySelector("[data-item='e1']") as HTMLElement;
    expect(accepted.textContent).toContain("challan.pdf");
    expect(accepted.textContent).toContain("1.5 KB");
    expect(accepted.textContent).toContain("Priya Shah");
    expect(accepted.querySelector("time")?.getAttribute("datetime")).toBe("2026-10-01T09:00:00Z");
    expect(accepted.querySelector("time")?.textContent).toBe("1 Oct 2026, 2:30 pm IST");
    const tones = [...container.querySelectorAll("[data-item]")].map((row) => [
      row.querySelector("[data-slot='status-chip']")?.textContent,
      row.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone"),
    ]);
    expect(tones).toEqual([
      ["Accepted", "success"],
      ["Rejected", "danger"],
      ["Submitted", "info"],
    ]);
    expect(container.querySelector("[data-item='e3']")?.textContent).toContain("2 MB");
    expect(screen.getByRole("tab", { name: "All files" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("keeps the rejected count neutral when nothing was rejected", () => {
    const { container } = render(
      <EvidenceView
        evidence={{ ...evidence, items: evidence.items.filter((item) => item.id !== "e2") }}
      />,
    );
    expect(figures(container).Rejected).toEqual({ value: "0", tone: "neutral" });
  });

  it("offers the upload form only when an upload action is given, and posts the file field", async () => {
    const uploadAction = vi.fn<(formData: FormData) => Promise<void>>(async () => undefined);
    const { container } = render(
      <EvidenceView
        evidence={{ obligationName: "TDS return", dueDate: null, items: [] }}
        uploadAction={uploadAction}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Upload evidence" })).toBeDefined();
    const input = screen.getByLabelText(/^File/) as HTMLInputElement;
    expect(input.type).toBe("file");
    expect(input.name).toBe(EVIDENCE_UPLOAD_FIELDS.file);
    expect(input.required).toBe(true);
    expect(input.getAttribute("aria-describedby")).toBeTruthy();
    expect(
      screen.getByText("Choose one file, such as a payment challan or a filing acknowledgement."),
    ).toBeDefined();
    expect(screen.getByRole("button", { name: "Upload" }).getAttribute("type")).toBe("submit");
    expect(screen.getByRole("heading", { level: 2, name: "No evidence yet" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();

    // jsdom keeps a required file input invalid whatever is chosen, so the form is submitted
    // directly; the browser's own check stops an empty submission.
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    await waitFor(() => expect(uploadAction).toHaveBeenCalledTimes(1));
    expect(uploadAction.mock.calls[0]?.[0].get(EVIDENCE_UPLOAD_FIELDS.file)).toBeInstanceOf(File);
  });
});
