import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Route } from "next";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OBLIGATION_STATUS_FIELDS, type Obligation } from "../model/obligations";
import { ObligationDetailView } from "./obligation-detail-view";

/** Noon on 15 Oct 2000 in India. */
const NOW = new Date("2000-10-15T06:30:00Z");

const EVIDENCE_HREF = "/b/biz_1/obligations/obl_1/evidence" as Route;

function obligation(overrides: Partial<Obligation> = {}): Obligation {
  return {
    id: "obl_1",
    businessId: "biz_1",
    title: "File example return 1 for the month",
    status: "open",
    dueAt: "2000-10-12T18:29:59Z",
    evidenceType: "filing_acknowledgement",
    steps: [
      "Reconcile the month's supplies",
      "Pay the tax due",
      "File example return 1 on the example portal",
    ],
    ruleVersionId: "rv_1",
    decisionId: "dec_1",
    periodLabel: "2000-08",
    periodStart: "2000-08-01",
    periodEnd: "2000-09-01",
    closedAt: null,
    closedReason: null,
    profileVersion: null,
    assigneeId: null,
    ...overrides,
  };
}

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

function fact(label: string): string | null | undefined {
  const facts = screen.getByRole("heading", { name: "Details" }).parentElement as HTMLElement;
  const term = [...facts.querySelectorAll("dt")].find((dt) => dt.textContent === label);
  return term?.nextElementSibling?.textContent;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("ObligationDetailView", () => {
  it("shows an overdue open obligation with its steps, details, evidence link and status buttons", async () => {
    const statusAction = vi.fn<(formData: FormData) => Promise<void>>(async () => undefined);
    const { container } = render(
      <ObligationDetailView
        obligation={obligation()}
        evidenceHref={EVIDENCE_HREF}
        statusAction={statusAction}
        now={NOW}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "File example return 1 for the month" }),
    ).toBeDefined();
    expect(screen.getByText("Period 2000-08: 1 Aug 2000 to 31 Aug 2000")).toBeDefined();
    expect(screen.getByRole("link", { name: "Evidence" }).getAttribute("href")).toBe(EVIDENCE_HREF);
    expect(figures(container)).toEqual({
      Status: { value: "Open", tone: "info" },
      Due: { value: "12 Oct 2000", tone: "danger" },
      "Evidence needed": { value: "Filing acknowledgement", tone: "neutral" },
    });
    expect(screen.getByText("Overdue by 3 days")).toBeDefined();

    const update = screen.getByRole("heading", { level: 2, name: "Update the status" })
      .parentElement as HTMLElement;
    expect(
      within(update)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Start work", "Mark as done"]);
    const done = container.querySelector("form[data-change='done']") as HTMLFormElement;
    expect(
      done.querySelector<HTMLInputElement>(`input[name='${OBLIGATION_STATUS_FIELDS.status}']`)
        ?.value,
    ).toBe("done");

    const steps = screen.getByRole("heading", { level: 2, name: "What to do" })
      .parentElement as HTMLElement;
    expect(
      within(steps)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Reconcile the month's supplies",
      "Pay the tax due",
      "File example return 1 on the example portal",
    ]);
    expect(fact("Rule version")).toContain("rv_1");
    expect(fact("Applicability decision")).toContain("dec_1");
    expect(screen.getByRole("button", { name: "Copy Rule version" })).toBeDefined();
    expect(fact("Closed")).toBeUndefined();
    expect(await runAxe(container)).toHaveNoViolations();

    await userEvent.setup().click(screen.getByRole("button", { name: "Start work" }));
    await waitFor(() => expect(statusAction).toHaveBeenCalledTimes(1));
    expect(statusAction.mock.calls[0]?.[0].get(OBLIGATION_STATUS_FIELDS.status)).toBe(
      "in_progress",
    );
  });

  it("only offers to mark an obligation in progress done", () => {
    render(
      <ObligationDetailView
        obligation={obligation({ status: "in_progress", dueAt: "2000-10-20T18:29:59Z" })}
        statusAction={vi.fn(async () => undefined)}
        now={NOW}
      />,
    );
    expect(screen.getByRole("button", { name: "Mark as done" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Start work" })).toBeNull();
    expect(screen.getByText("Due in 5 days")).toBeDefined();
    expect(screen.queryByRole("link", { name: "Evidence" })).toBeNull();
  });

  it("offers no status buttons without a status action", () => {
    render(<ObligationDetailView obligation={obligation()} now={NOW} />);
    expect(screen.queryByRole("heading", { name: "Update the status" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Start work" })).toBeNull();
  });

  it("shows when and why a closed obligation was closed, with nothing left to change", async () => {
    const { container } = render(
      <ObligationDetailView
        obligation={obligation({
          status: "done",
          closedAt: "2000-10-10T05:00:00Z",
          closedReason: "completed",
        })}
        statusAction={vi.fn(async () => undefined)}
        now={NOW}
      />,
    );
    expect(figures(container).Status).toEqual({ value: "Done", tone: "success" });
    expect(figures(container).Due).toEqual({ value: "12 Oct 2000", tone: "neutral" });
    expect(container.querySelector("[data-slot='stat-card'] p")).toBeNull();
    expect(fact("Closed")).toBe("Completed on 10 Oct 2000");
    expect(screen.queryByRole("heading", { name: "Update the status" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("gives the closing date alone when the service names no reason", () => {
    render(
      <ObligationDetailView
        obligation={obligation({ status: "waived", closedAt: "2000-10-10T05:00:00Z" })}
        now={NOW}
      />,
    );
    expect(fact("Closed")).toBe("10 Oct 2000");
  });

  it("words a one-off obligation without a due date, steps or named evidence", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const { container } = render(
      <ObligationDetailView
        obligation={obligation({
          periodLabel: null,
          periodStart: null,
          periodEnd: null,
          dueAt: null,
          steps: [],
          evidenceType: "",
        })}
      />,
    );
    expect(screen.getByText("A one-off duty: it does not recur.")).toBeDefined();
    expect(figures(container)).toEqual({
      Status: { value: "Open", tone: "info" },
      Due: { value: "No due date", tone: "neutral" },
      "Evidence needed": { value: "Not specified", tone: "neutral" },
    });
    expect(screen.getByText("No steps are listed for this obligation.")).toBeDefined();
    expect(container.querySelector("ol")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
