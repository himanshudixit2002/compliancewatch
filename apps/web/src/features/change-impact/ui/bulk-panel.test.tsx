import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/obligation-fixture";
import { BulkPanel, type BulkAction } from "./bulk-panel";
import type { BulkSummary } from "./bulk-shared";

const FORM_UUID = "5d1c8b2e-3f4a-4b6c-8d9e-0f1a2b3c4d5e";
const TARGETS = [
  { businessId: REGISTRATION_ID, label: "Example business: GSTIN example" },
  { businessId: ENTITY_ID, label: "Example business: the client itself" },
];

function summary(replayed: boolean): BulkSummary {
  return {
    message: replayed ? "Example already sent." : "Example sent.",
    replayed,
    businesses: [
      {
        businessId: REGISTRATION_ID,
        outcome: "queued",
        outcomeLabel: "Queued",
        people: "1 told now",
      },
      {
        businessId: ENTITY_ID,
        outcome: "not_affected",
        outcomeLabel: "Not affected",
        people: "No open obligation of the change",
      },
    ],
  };
}

function renderPanel(action: BulkAction, props: Partial<Parameters<typeof BulkPanel>[0]> = {}) {
  return render(
    <BulkPanel
      action={action}
      targets={TARGETS}
      cut={false}
      idempotencyInput={<input type="hidden" name="idempotency_key" value={FORM_UUID} />}
      {...props}
    />,
  );
}

describe("BulkPanel", () => {
  it("sends the businesses with the page's key after the dialog, and sends the same request again", async () => {
    const sent: [string, string[]][] = [];
    let calls = 0;
    const action = vi.fn<BulkAction>(async (_state, formData) => {
      sent.push([
        String(formData.get("idempotency_key")),
        formData.getAll("business_id").map(String),
      ]);
      calls += 1;
      return { status: "ok", value: summary(calls > 1), message: "x" };
    });
    const { container } = renderPanel(action);
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Send the change card to 2 affected businesses" }),
    );
    const dialog = screen.getByRole("dialog", { name: "Send the change card?" });
    expect(dialog.textContent).toContain("nobody gets it twice");
    await user.click(within(dialog).getByRole("button", { name: "Send the change card" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example sent."));
    const result = container.querySelector("[data-slot='bulk-result']") as HTMLElement;
    const queued = result.querySelector(`[data-business='${REGISTRATION_ID}']`) as HTMLElement;
    expect(queued.getAttribute("data-outcome")).toBe("queued");
    expect(queued.textContent).toContain("Example business: GSTIN example");
    expect(queued.textContent).toContain("1 told now");
    expect(await runAxe(result)).toHaveNoViolations();
    await user.click(
      screen.getByRole("button", { name: "Send the change card to 2 affected businesses" }),
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Send the change card" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Example already sent."),
    );
    expect(
      container.querySelector("[data-slot='bulk-outcome']")?.getAttribute("data-replayed"),
    ).toBe("true");
    expect(sent).toEqual([
      [FORM_UUID, [REGISTRATION_ID, ENTITY_ID]],
      [FORM_UUID, [REGISTRATION_ID, ENTITY_ID]],
    ]);
  });

  it("keeps a request whose answer never arrived and sends exactly it again", async () => {
    const forms: FormData[] = [];
    const action = vi
      .fn<BulkAction>()
      .mockImplementationOnce(async (_state, formData) => {
        forms.push(formData);
        throw new TypeError("Example connection dropped");
      })
      .mockImplementationOnce(async (_state, formData) => {
        forms.push(formData);
        return { status: "ok", value: summary(true) };
      });
    renderPanel(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Send the change card/ }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Send the change card" }),
    );
    await waitFor(() => expect(screen.getByText("No answer arrived")).toBeDefined());
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("Example already sent.")).toBeDefined());
    expect(forms[1]).toBe(forms[0]);
  });

  it("says when bulk cards are off on the service, with its problem", async () => {
    const action = vi.fn<BulkAction>(async () => ({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:notification-bulk-disabled",
        title: "Example bulk off",
        correlationId: "req-example-8",
      },
      formErrors: ["Example switched off on the notification service."],
    }));
    renderPanel(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Send the change card/ }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Send the change card" }),
    );
    await waitFor(() => expect(screen.getByText("Example bulk off")).toBeDefined());
    expect(screen.getByText("req-example-8")).toBeDefined();
    expect(screen.getByText("Example switched off on the notification service.")).toBeDefined();
  });

  it("offers nothing when no client is affected, and says when the card names only some", async () => {
    const { rerender, container } = renderPanel(vi.fn<BulkAction>(), { targets: [] });
    expect(screen.getByText("No client is affected, so there is nobody to tell.")).toBeDefined();
    expect(screen.queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <BulkPanel
        action={vi.fn<BulkAction>()}
        targets={TARGETS.slice(0, 1)}
        cut
        idempotencyInput={<input type="hidden" name="idempotency_key" value={FORM_UUID} />}
      />,
    );
    expect(screen.getByText("Not every affected business is named")).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Send the change card to 1 affected business" }),
    ).toBeDefined();
  });
});
