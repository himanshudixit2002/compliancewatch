import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { PreferenceForm, type PreferenceFormProps } from "./preference-form";

const FIELDS = {
  channel: "channel",
  optedIn: "opted_in",
  language: "language",
  quietStart: "quiet_hours_start",
  quietEnd: "quiet_hours_end",
};

function renderForm(overrides: Partial<PreferenceFormProps> = {}) {
  return render(
    <PreferenceForm
      action={vi.fn(async (): Promise<ActionState> => ({ status: "idle" }))}
      channel="whatsapp"
      recipient="+910000000000"
      fields={FIELDS}
      values={{ optedIn: true, language: "hi", quietHoursStart: "22:00", quietHoursEnd: "07:00" }}
      languages={[
        { value: "en", label: "English" },
        { value: "hi", label: "Hindi" },
      ]}
      consentGiven
      purposeLabel="WhatsApp reminders"
      consentsHref="/settings/consents"
      {...overrides}
    />,
  );
}

describe("PreferenceForm", () => {
  it("starts from the recorded values and names itself after the recipient", async () => {
    const { container } = renderForm();
    const form = screen.getByRole("form", { name: "Preference for +910000000000" });
    expect(screen.getByRole("radio", { name: "Send reminders" }).getAttribute("aria-checked")).toBe(
      "true",
    );
    expect((screen.getByLabelText(/Language/) as HTMLSelectElement).value).toBe("hi");
    expect((screen.getByLabelText(/From/) as HTMLInputElement).value).toBe("22:00");
    expect((screen.getByLabelText(/Until/) as HTMLInputElement).value).toBe("07:00");
    expect(screen.getByRole("group", { name: "Quiet hours (IST)" })).toBeDefined();
    expect(form.textContent).not.toContain("consent not on file");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("posts every field and says what was saved", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const action = vi.fn(async (_state: ActionState, formData: FormData): Promise<ActionState> => {
      sent = formData;
      return { status: "ok", message: "Example saved message." };
    });
    renderForm({ action });
    await user.click(screen.getByRole("radio", { name: "Do not send reminders" }));
    await user.selectOptions(screen.getByLabelText(/Language/), "en");
    await user.click(screen.getByRole("button", { name: "Save the preference" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Example saved message."),
    );
    expect(Object.fromEntries(sent?.entries() ?? [])).toEqual({
      channel: "whatsapp",
      opted_in: "out",
      language: "en",
      quiet_hours_start: "22:00",
      quiet_hours_end: "07:00",
    });
  });

  it("says why reminders cannot be switched on without the consent, and shows refusals", async () => {
    const user = userEvent.setup();
    const { container } = renderForm({
      consentGiven: false,
      action: vi.fn(async (): Promise<ActionState> => ({
        status: "error",
        problem: { type: "urn:example", title: "Example problem" },
        formErrors: ["Example form error."],
        fieldErrors: {
          opted_in: ["Example choice error."],
          quiet_hours_start: ["Example time error."],
        },
      })),
    });
    expect(container.textContent).toContain("WhatsApp reminders: consent not on file");
    expect(screen.getByRole("link", { name: "Consents" }).getAttribute("href")).toBe(
      "/settings/consents",
    );
    await user.click(screen.getByRole("button", { name: "Save the preference" }));
    await waitFor(() => expect(screen.getByText("Example form error.")).toBeDefined());
    expect(screen.getByText("Example problem")).toBeDefined();
    expect(screen.getByText("Example choice error.")).toBeDefined();
    expect(screen.getByRole("radiogroup").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Example time error.")).toBeDefined();
  });

  it("puts the submitted values back after a refusal", async () => {
    const user = userEvent.setup();
    renderForm({
      action: vi.fn(async (): Promise<ActionState> => ({
        status: "error",
        formErrors: ["Example form error."],
      })),
    });
    await user.selectOptions(screen.getByLabelText(/Language/), "en");
    await user.click(screen.getByRole("radio", { name: "Do not send reminders" }));
    await user.click(screen.getByRole("button", { name: "Save the preference" }));
    await screen.findByText("Example form error.");
    expect((screen.getByLabelText(/Language/) as HTMLSelectElement).value).toBe("en");
    expect(
      screen.getByRole("radio", { name: "Do not send reminders" }).getAttribute("aria-checked"),
    ).toBe("true");
  });
});
