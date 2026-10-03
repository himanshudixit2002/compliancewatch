import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { formatDate } from "@/shared/lib/dates";
import type { DataRequest } from "../model/data-rights";
import { DataRightsView } from "./data-rights-view";

type Action = (formData: FormData) => Promise<void>;

const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "owner.settings.data-rights", href: "/settings/data-rights", label: "Data rights" },
];
const TABS = [{ id: "owner.settings.consents", href: "/settings/consents", label: "Consents" }];

const REQUESTS: DataRequest[] = [
  {
    id: "dr_copy_done",
    kind: "export",
    status: "completed",
    requestedAt: "2026-08-03T05:00:00Z",
    dueBy: "2026-09-02T05:00:00Z",
    closedAt: "2026-08-20T05:00:00Z",
  },
  {
    id: "dr_erase",
    kind: "deletion",
    status: "declined",
    requestedAt: "2026-05-04T05:00:00Z",
    dueBy: "2026-06-03T05:00:00Z",
    closedAt: "2026-05-10T05:00:00Z",
  },
  {
    id: "dr_copy_open",
    kind: "export",
    status: "in_progress",
    requestedAt: "2026-10-01T05:00:00Z",
    dueBy: "2026-10-31T05:00:00Z",
    closedAt: null,
  },
];

const exportHref = (id: string) => `/settings/data-rights/${id}/export` as Route;

function cells(container: HTMLElement, id: string): (string | null)[] {
  const row = container.querySelector(`[data-request='${id}']`) as HTMLElement;
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

describe("DataRightsView", () => {
  it("lists every request newest first with its status and dates, and no forms", async () => {
    const { container } = render(
      <DataRightsView title="Data rights" requests={REQUESTS} crumbs={CRUMBS} tabs={TABS} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Data rights" })).toBeDefined();
    expect(screen.getByText(/Digital Personal Data Protection Act/)).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "Your requests" })).toBeDefined();
    expect(screen.getByText("Requests for this account, newest first")).toBeDefined();
    expect(
      [...container.querySelectorAll("tbody tr")].map((tr) => tr.getAttribute("data-request")),
    ).toEqual(["dr_copy_open", "dr_copy_done", "dr_erase"]);
    expect(cells(container, "dr_copy_open")).toEqual([
      "Copy of your data",
      "In progress",
      formatDate("2026-10-01T05:00:00Z"),
      formatDate("2026-10-31T05:00:00Z"),
      "Not yet",
    ]);
    expect(cells(container, "dr_erase")).toEqual([
      "Deletion of your data",
      "Declined",
      formatDate("2026-05-04T05:00:00Z"),
      formatDate("2026-06-03T05:00:00Z"),
      formatDate("2026-05-10T05:00:00Z"),
    ]);
    const tones = [...container.querySelectorAll("[data-slot='status-chip']")].map((chip) =>
      chip.getAttribute("data-tone"),
    );
    expect(tones).toEqual(["warning", "success", "danger"]);
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link", { name: /Download/ })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("links to the download of a completed copy only", () => {
    render(
      <DataRightsView
        title="Data rights"
        requests={REQUESTS}
        crumbs={CRUMBS}
        tabs={TABS}
        exportHref={exportHref}
      />,
    );
    const links = screen.getAllByRole("link", { name: /^Download/ });
    expect(links.map((link) => link.textContent)).toEqual([
      `Download the copy requested on ${formatDate("2026-08-03T05:00:00Z")}`,
    ]);
    expect(links[0]?.getAttribute("href")).toBe("/settings/data-rights/dr_copy_done/export");
  });

  it("holds back a second request of a kind that is open and asks before a deletion", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const requestAction = vi.fn<Action>(async (formData) => {
      sent = formData;
    });
    const { container } = render(
      <DataRightsView
        title="Data rights"
        requests={REQUESTS}
        crumbs={CRUMBS}
        tabs={TABS}
        requestAction={requestAction}
      />,
    );
    const copy = screen.getByRole("region", { name: "Get a copy of your data" });
    expect(copy.textContent).toContain(
      `Your request of ${formatDate("2026-10-01T05:00:00Z")} is open. It is due by ${formatDate("2026-10-31T05:00:00Z")}.`,
    );
    expect(within(copy).queryByRole("button")).toBeNull();

    const deletion = screen.getByRole("region", { name: "Delete your data" });
    const understood = within(deletion).getByRole("checkbox", {
      name: "I understand that deletion cannot be undone and ends the service for this account.",
    });
    expect(understood.hasAttribute("required")).toBe(true);
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(understood);
    await user.click(within(deletion).getByRole("button", { name: "Ask for deletion" }));
    await waitFor(() => expect(requestAction).toHaveBeenCalledTimes(1));
    expect(sent?.get("kind")).toBe("deletion");
    expect(sent?.get("confirm_deletion")).toBe("yes");
  });

  it("asks for a copy, and explains that there are no requests yet", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const requestAction = vi.fn<Action>(async (formData) => {
      sent = formData;
    });
    const { container } = render(
      <DataRightsView
        title="Data rights"
        requests={[]}
        crumbs={CRUMBS}
        tabs={TABS}
        requestAction={requestAction}
      />,
    );
    expect(screen.getByRole("heading", { level: 3, name: "No requests yet" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.querySelector("[data-slot='open-request']")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(screen.getByRole("button", { name: "Ask for a copy" }));
    await waitFor(() => expect(requestAction).toHaveBeenCalledTimes(1));
    expect(sent?.get("kind")).toBe("export");
    expect(sent?.has("confirm_deletion")).toBe(false);
  });
});
