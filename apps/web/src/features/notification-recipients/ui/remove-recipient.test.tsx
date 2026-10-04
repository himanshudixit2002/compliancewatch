import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { RemoveRecipient } from "./remove-recipient";

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

const RECIPIENT = "00000000-0000-4000-8000-0000000000e1";
const BUSINESS = "00000000-0000-4000-8000-0000000000b1";
const FIELDS = { recipientId: "recipient_id", returnBusiness: "return_business" };

describe("RemoveRecipient", () => {
  it("asks first, saying what is deleted and what stays, then sends the recipient's id", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const action = vi.fn<Action>(async (_state, formData) => {
      sent = formData;
      return { status: "idle" };
    });
    render(
      <RemoveRecipient
        action={action}
        recipientId={RECIPIENT}
        name="Example desk"
        returnBusiness={BUSINESS}
        fields={FIELDS}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Remove Example desk" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Example desk?" });
    expect(dialog.textContent).toContain("Each address keeps its opt-in or opt-out.");
    expect(await runAxe(dialog)).toHaveNoViolations();
    await user.click(screen.getByRole("button", { name: "Remove the recipient" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    expect(sent?.get("recipient_id")).toBe(RECIPIENT);
    expect(sent?.get("return_business")).toBe(BUSINESS);
  });

  it("keeps the dialog open with the problem when the removal is refused", async () => {
    const user = userEvent.setup();
    const action = vi.fn<Action>(async () => ({
      status: "error",
      problem: { type: "urn:example", title: "Example refusal", correlationId: "req-2" },
      formErrors: ["Example form error."],
    }));
    render(
      <RemoveRecipient
        action={action}
        recipientId={RECIPIENT}
        name="Example desk"
        returnBusiness={BUSINESS}
        fields={FIELDS}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Remove Example desk" }));
    await user.click(await screen.findByRole("button", { name: "Remove the recipient" }));
    await waitFor(() => expect(screen.getByText("Example refusal")).toBeDefined());
    expect(screen.getByText("Example form error.")).toBeDefined();
    expect(screen.getByRole("dialog")).toBeDefined();
  });
});
