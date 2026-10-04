import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { RecipientForm, type RecipientFormData, type RecipientFormProps } from "./recipient-form";

type Action = (state: ActionState, formData: FormData) => Promise<ActionState>;

const BUSINESS = "00000000-0000-4000-8000-0000000000b1";
const OTHER = "00000000-0000-4000-8000-0000000000b2";

const FORM: RecipientFormData = {
  mode: "add",
  recipientId: "00000000-0000-4000-8000-0000000000e9",
  name: "",
  values: {
    role: "owner",
    language: "en",
    digestMode: "off",
    orgLabel: "",
    addresses: [],
    businessIds: [BUSINESS],
  },
  roles: [
    { value: "owner", label: "Owner" },
    { value: "staff", label: "Staff" },
  ],
  languages: [
    { value: "en", label: "English" },
    { value: "hi", label: "Hindi" },
  ],
  businesses: [
    { value: BUSINESS, label: "Example business" },
    { value: OTHER, label: "Example second business" },
  ],
  addressRows: 2,
};

const FIELDS: RecipientFormProps["fields"] = {
  recipientId: "recipient_id",
  returnBusiness: "return_business",
  role: "role",
  language: "language",
  digestMode: "digest_mode",
  orgLabel: "org_label",
  businesses: "businesses",
  addresses: ["addresses.0.address", "addresses.1.address"],
  channels: ["addresses.0.channel", "addresses.1.channel"],
};

function renderForm(
  action: Action,
  form: RecipientFormData = FORM,
  cancelHref: string | null = null,
) {
  return render(
    <RecipientForm
      action={action}
      form={form}
      returnBusiness={BUSINESS}
      fields={FIELDS}
      channels={[
        { value: "whatsapp", label: "WhatsApp" },
        { value: "email", label: "Email" },
      ]}
      digestModes={[
        { value: "off", label: "As they happen" },
        { value: "daily", label: "Daily digest" },
      ]}
      cancelHref={cancelHref}
    />,
  );
}

describe("RecipientForm", () => {
  it("sends the recipient's choices with its id and the business to return to", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const action = vi.fn<Action>(async (_state, formData) => {
      sent = formData;
      return { status: "idle" };
    });
    const { container } = renderForm(action);
    expect((screen.getByLabelText("Channel of address 1") as HTMLSelectElement).value).toBe(
      "whatsapp",
    );
    expect((screen.getByLabelText("Channel of address 2") as HTMLSelectElement).value).toBe(
      "email",
    );
    await user.selectOptions(screen.getByLabelText(/^Role/), "staff");
    await user.type(screen.getByLabelText("Address 1"), "+910000000001");
    await user.selectOptions(screen.getByLabelText(/^Delivery/), "daily");
    await user.click(screen.getByRole("checkbox", { name: "Example second business" }));
    await user.click(screen.getByRole("button", { name: "Add the recipient" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    expect(sent?.get("recipient_id")).toBe(FORM.recipientId);
    expect(sent?.get("return_business")).toBe(BUSINESS);
    expect(sent?.get("role")).toBe("staff");
    expect(sent?.get("digest_mode")).toBe("daily");
    expect(sent?.get("addresses.0.address")).toBe("+910000000001");
    expect(sent?.getAll("businesses")).toEqual([BUSINESS, OTHER]);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("keeps what was sent after a refusal, marks the fields and moves focus to the summary", async () => {
    const user = userEvent.setup();
    const action = vi.fn<Action>(async () => ({
      status: "error",
      fieldErrors: {
        "addresses.0.address": ["Enter a WhatsApp number with its country code, starting with +."],
      },
    }));
    const { container } = renderForm(action);
    await user.type(screen.getByLabelText("Address 1"), "0000");
    await user.type(screen.getByLabelText(/^Organisation/), "Example firm");
    await user.click(screen.getByRole("button", { name: "Add the recipient" }));
    await waitFor(() => expect(screen.getByText("The recipient was not saved")).toBeDefined());
    const address = screen.getByLabelText("Address 1") as HTMLInputElement;
    expect(address.value).toBe("0000");
    expect(address.getAttribute("aria-invalid")).toBe("true");
    expect((screen.getByLabelText(/^Organisation/) as HTMLInputElement).value).toBe("Example firm");
    expect(screen.getByText("Correct the fields marked below and save again.")).toBeDefined();
    await waitFor(() =>
      expect(document.activeElement).toBe(
        container.querySelector("[data-slot='recipient-form-summary']"),
      ),
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the service's problem and a form-level refusal", async () => {
    const user = userEvent.setup();
    const action = vi.fn<Action>(async () => ({
      status: "error",
      problem: {
        type: "urn:example",
        title: "Example problem",
        detail: "Example detail",
        correlationId: "req-1",
      },
      formErrors: ["This form is out of date. Reload the page and try again."],
    }));
    renderForm(action);
    await user.click(screen.getByRole("button", { name: "Add the recipient" }));
    await waitFor(() => expect(screen.getByText("Example problem")).toBeDefined());
    expect(screen.getByText("Example detail")).toBeDefined();
    expect(screen.getByText("req-1")).toBeDefined();
    expect(
      screen.getByText("This form is out of date. Reload the page and try again."),
    ).toBeDefined();
  });

  it("changes a recipient with its addresses filled in and a way back", () => {
    renderForm(
      vi.fn<Action>(),
      {
        ...FORM,
        mode: "change",
        name: "Example desk",
        values: {
          ...FORM.values,
          addresses: [{ channel: "email", address: "desk@example.com" }],
          businessIds: [OTHER],
        },
      },
      "/settings/notifications/recipients",
    );
    expect(screen.getByRole("form", { name: "Change Example desk" })).toBeDefined();
    expect((screen.getByLabelText("Address 1") as HTMLInputElement).value).toBe("desk@example.com");
    expect((screen.getByLabelText("Channel of address 1") as HTMLSelectElement).value).toBe(
      "email",
    );
    expect(
      screen
        .getByRole("checkbox", { name: "Example second business" })
        .getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.getByRole("link", { name: "Cancel" }).getAttribute("href")).toBe(
      "/settings/notifications/recipients",
    );
    expect(screen.getByRole("button", { name: "Save the recipient" })).toBeDefined();
  });
});
