import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { RecipientForm } from "./recipient-form";

const FIELDS = { channel: "channel", recipient: "recipient" };

describe("RecipientForm", () => {
  it("posts the channel and the number, and shows the error on the field", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const action = vi.fn(async (_state: ActionState, formData: FormData): Promise<ActionState> => {
      sent = formData;
      return { status: "error", fieldErrors: { recipient: ["Example field error."] } };
    });
    const { container } = render(
      <RecipientForm
        action={action}
        channel="whatsapp"
        label="WhatsApp number"
        formLabel="Example recipient form"
        help="Example help."
        inputType="tel"
        fields={FIELDS}
      />,
    );
    const input = screen.getByLabelText(/WhatsApp number/);
    expect(input.getAttribute("type")).toBe("tel");
    await user.type(input, "+910000000000");
    await user.click(screen.getByRole("button", { name: "Show its preference" }));
    await waitFor(() => expect(screen.getByText("Example field error.")).toBeDefined());
    expect(sent?.get("channel")).toBe("whatsapp");
    expect(sent?.get("recipient")).toBe("+910000000000");
    // The refused number is put back so it can be corrected.
    expect((screen.getByLabelText(/WhatsApp number/) as HTMLInputElement).value).toBe(
      "+910000000000",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the service's problem and a form error on the field", async () => {
    const user = userEvent.setup();
    render(
      <RecipientForm
        action={vi.fn(async (): Promise<ActionState> => ({
          status: "error",
          problem: { type: "urn:example", title: "Example problem", correlationId: "req-1" },
          formErrors: ["Example form error."],
        }))}
        channel="email"
        label="Email address"
        formLabel="Example recipient form"
        help="Example help."
        inputType="email"
        fields={FIELDS}
      />,
    );
    expect(screen.getByLabelText(/Email address/).getAttribute("autocomplete")).toBe("email");
    await user.click(screen.getByRole("button", { name: "Show its preference" }));
    await waitFor(() => expect(screen.getByText("Example problem")).toBeDefined());
    expect(screen.getByText("Example form error.")).toBeDefined();
  });
});
