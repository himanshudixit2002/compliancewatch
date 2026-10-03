import type { Route } from "next";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { formatDateTime } from "@/shared/lib/dates";
import { SOURCE_KEY_FIELD, type PipelineSource } from "../model/sources";
import { AdminSourcesView } from "./sources-view";

const hrefFor = (key: string) => `/admin/sources/${key}` as Route;

const SOURCES: PipelineSource[] = [
  {
    key: "cbic_notifications",
    name: "CBIC notifications",
    site: "taxinformation.cbic.gov.in",
    documentType: "notification",
    status: "healthy",
    lastFetchedAt: "2026-10-02T04:00:00Z",
    documentCount: 1234567,
  },
  {
    key: "gstcouncil_press",
    name: "GST Council press releases",
    site: "gstcouncil.gov.in",
    documentType: "press_release",
    status: "fetching",
    lastFetchedAt: "2026-10-01T04:00:00Z",
    documentCount: 87,
  },
  {
    key: "mahagst_notifications",
    name: "Maharashtra GST notifications",
    site: "mahagst.gov.in",
    documentType: "notification",
    status: "failing",
    lastFetchedAt: null,
    documentCount: 0,
  },
];

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

function row(container: HTMLElement, key: string): HTMLElement {
  return container.querySelector(`[data-source='${key}']`) as HTMLElement;
}

describe("AdminSourcesView", () => {
  it("counts the sources and lists each with its type, state, last fetch and documents", async () => {
    const { container } = render(<AdminSourcesView sources={SOURCES} hrefFor={hrefFor} />);
    expect(screen.getByRole("heading", { level: 1, name: "Sources" })).toBeDefined();
    expect(figures(container)).toEqual({
      Sources: { value: "3", tone: "info" },
      Healthy: { value: "1", tone: "success" },
      Failing: { value: "1", tone: "danger" },
    });
    expect(screen.getByRole("table", { name: "Sources the pipeline fetches from" })).toBeDefined();
    expect(screen.getAllByRole("columnheader").map((head) => head.textContent)).toEqual([
      "Source",
      "Document type",
      "Status",
      "Last fetched",
      "Documents",
    ]);

    const cbic = row(container, "cbic_notifications");
    expect(
      within(cbic).getByRole("link", { name: "CBIC notifications" }).getAttribute("href"),
    ).toBe("/admin/sources/cbic_notifications");
    expect(cbic.textContent).toContain("taxinformation.cbic.gov.in");
    expect(cbic.textContent).toContain("Notifications");
    expect(cbic.querySelector("[data-slot='status-chip']")?.textContent).toBe("Healthy");
    expect(cbic.textContent).toContain(formatDateTime("2026-10-02T04:00:00Z"));
    expect(cbic.textContent).toContain("12,34,567");

    const press = row(container, "gstcouncil_press");
    expect(press.textContent).toContain("Press releases");
    expect(press.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "info",
    );
    const mahagst = row(container, "mahagst_notifications");
    expect(mahagst.textContent).toContain("Never");
    expect(mahagst.querySelector("[data-slot='status-chip']")?.textContent).toBe("Failing");
    expect(screen.queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers a fetch for each source not already fetching and posts its key", async () => {
    const user = userEvent.setup();
    const fetchAction = vi.fn<(formData: FormData) => Promise<void>>(async () => undefined);
    const { container } = render(<AdminSourcesView sources={SOURCES} fetchAction={fetchAction} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByRole("columnheader", { name: "Fetch" })).toBeDefined();
    expect(within(row(container, "gstcouncil_press")).queryByRole("button")).toBeNull();
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Fetch now CBIC notifications",
      "Fetch now Maharashtra GST notifications",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("button", { name: /^Fetch now\s*Maharashtra GST/ }));
    await waitFor(() => expect(fetchAction).toHaveBeenCalledTimes(1));
    const formData = fetchAction.mock.calls[0]?.[0];
    expect(formData?.get(SOURCE_KEY_FIELD)).toBe("mahagst_notifications");
  });

  it("keeps the failing count neutral when every source is healthy", () => {
    const { container } = render(<AdminSourcesView sources={SOURCES.slice(0, 1)} />);
    expect(figures(container).Failing).toEqual({ value: "0", tone: "neutral" });
    expect(screen.getByText("CBIC notifications").tagName).toBe("SPAN");
  });

  it("shows the empty state before any source is set up", async () => {
    const { container } = render(<AdminSourcesView sources={[]} fetchAction={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2, name: "No sources" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
