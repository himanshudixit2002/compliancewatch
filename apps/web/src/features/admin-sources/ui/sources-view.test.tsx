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
    key: "example_notices",
    name: "Example notices",
    site: "notices.example.com",
    documentType: "notification",
    status: "healthy",
    lastFetchedAt: "2000-10-02T04:00:00Z",
    documentCount: 1234567,
  },
  {
    key: "example_press",
    name: "Example press releases",
    site: "press.example.com",
    documentType: "press_release",
    status: "fetching",
    lastFetchedAt: "2000-10-01T04:00:00Z",
    documentCount: 87,
  },
  {
    key: "example_state_notices",
    name: "Example state notices",
    site: "state.example.com",
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

    const notices = row(container, "example_notices");
    expect(
      within(notices).getByRole("link", { name: "Example notices" }).getAttribute("href"),
    ).toBe("/admin/sources/example_notices");
    expect(notices.textContent).toContain("notices.example.com");
    expect(notices.textContent).toContain("Notifications");
    expect(notices.querySelector("[data-slot='status-chip']")?.textContent).toBe("Healthy");
    expect(notices.textContent).toContain(formatDateTime("2000-10-02T04:00:00Z"));
    expect(notices.textContent).toContain("12,34,567");

    const press = row(container, "example_press");
    expect(press.textContent).toContain("Press releases");
    expect(press.querySelector("[data-slot='status-chip']")?.getAttribute("data-tone")).toBe(
      "info",
    );
    const stateNotices = row(container, "example_state_notices");
    expect(stateNotices.textContent).toContain("Never");
    expect(stateNotices.querySelector("[data-slot='status-chip']")?.textContent).toBe("Failing");
    expect(screen.queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers a fetch for each source not already fetching and posts its key", async () => {
    const user = userEvent.setup();
    const fetchAction = vi.fn<(formData: FormData) => Promise<void>>(async () => undefined);
    const { container } = render(<AdminSourcesView sources={SOURCES} fetchAction={fetchAction} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByRole("columnheader", { name: "Fetch" })).toBeDefined();
    expect(within(row(container, "example_press")).queryByRole("button")).toBeNull();
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Fetch now Example notices",
      "Fetch now Example state notices",
    ]);
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("button", { name: /^Fetch now\s*Example state/ }));
    await waitFor(() => expect(fetchAction).toHaveBeenCalledTimes(1));
    const formData = fetchAction.mock.calls[0]?.[0];
    expect(formData?.get(SOURCE_KEY_FIELD)).toBe("example_state_notices");
  });

  it("keeps the failing count neutral when every source is healthy", () => {
    const { container } = render(<AdminSourcesView sources={SOURCES.slice(0, 1)} />);
    expect(figures(container).Failing).toEqual({ value: "0", tone: "neutral" });
    expect(screen.getByText("Example notices").tagName).toBe("SPAN");
  });

  it("shows the empty state before any source is set up", async () => {
    const { container } = render(<AdminSourcesView sources={[]} fetchAction={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 2, name: "No sources" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='stat-card']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
