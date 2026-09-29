import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { ConsentForm, type ConsentFormOption } from "./consent-form";

function option(purpose: string, required: boolean, granted = false): ConsentFormOption {
  return {
    purpose,
    label: `Example label for ${purpose}.`,
    required,
    document: { title: "Example document", version: "9.9-draft" },
    documentHref: "/legal/privacy-notice",
    granted,
  };
}

const OPTIONS = [
  option("terms", true),
  option("privacy_notice", true),
  option("profile_processing", true),
  option("whatsapp_reminders", false),
  option("email_reminders", false),
  option("analytics", false, true),
];

describe("ConsentForm", () => {
  it("groups the required and optional boxes, each described by its document", async () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ status: "idle" }));
    const { container } = render(
      <ConsentForm
        action={action}
        options={OPTIONS}
        offerWhatsapp
        whatsappField="whatsapp_number"
      />,
    );
    expect(screen.getByRole("group", { name: "To use ComplianceWatch (required)" })).toBeDefined();
    expect(screen.getByRole("group", { name: "Reminders and analytics (optional)" })).toBeDefined();
    const terms = screen.getByRole("checkbox", { name: "Example label for terms." });
    expect(terms.getAttribute("aria-checked")).toBe("false");
    const hint = document.getElementById(terms.getAttribute("aria-describedby") as string);
    expect(hint?.textContent).toBe("Example document, version 9.9-draft");
    expect(hint?.querySelector("a")?.getAttribute("href")).toBe("/legal/privacy-notice");
    // A purpose already granted at the current version starts ticked.
    expect(
      screen
        .getByRole("checkbox", { name: "Example label for analytics." })
        .getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.queryByLabelText(/WhatsApp number/)).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the number field only while the WhatsApp box is ticked", async () => {
    const user = userEvent.setup();
    render(
      <ConsentForm
        action={vi.fn(async (): Promise<ActionState> => ({ status: "idle" }))}
        options={OPTIONS}
        offerWhatsapp
        whatsappField="whatsapp_number"
      />,
    );
    const whatsapp = screen.getByRole("checkbox", {
      name: "Example label for whatsapp_reminders.",
    });
    await user.click(whatsapp);
    const number = screen.getByLabelText(/WhatsApp number/);
    expect(number.getAttribute("name")).toBe("whatsapp_number");
    expect(number.getAttribute("type")).toBe("tel");
    await user.click(whatsapp);
    expect(screen.queryByLabelText(/WhatsApp number/)).toBeNull();
  });

  it("sends the ticked boxes and keeps them, with the field errors, after a refusal", async () => {
    const user = userEvent.setup();
    let submitted: FormData | undefined;
    const action = vi.fn(async (_state: ActionState, formData: FormData): Promise<ActionState> => {
      submitted = formData;
      return {
        status: "error",
        fieldErrors: {
          privacy_notice: ["Tick this box to continue."],
          whatsapp_number: ["Enter the WhatsApp number the reminders go to."],
        },
      };
    });
    const { container } = render(
      <ConsentForm
        action={action}
        options={OPTIONS}
        offerWhatsapp
        whatsappField="whatsapp_number"
      />,
    );
    await user.click(screen.getByRole("checkbox", { name: "Example label for terms." }));
    await user.click(
      screen.getByRole("checkbox", { name: "Example label for whatsapp_reminders." }),
    );
    await user.click(screen.getByRole("button", { name: "Agree and continue" }));
    await waitFor(() => expect(screen.getByText("Nothing was recorded")).toBeDefined());
    expect(submitted?.get("terms")).toBe("on");
    expect(submitted?.get("privacy_notice")).toBeNull();
    expect(screen.getByText("Check the fields marked below.")).toBeDefined();
    const privacy = screen.getByRole("checkbox", { name: "Example label for privacy_notice." });
    expect(privacy.getAttribute("aria-invalid")).toBe("true");
    expect(privacy.getAttribute("aria-describedby")).toMatch(/-error$/);
    expect(screen.getByText("Tick this box to continue.")).toBeDefined();
    expect(
      screen
        .getByRole("checkbox", { name: "Example label for terms." })
        .getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.getByLabelText(/WhatsApp number/).getAttribute("aria-invalid")).toBe("true");
    await waitFor(() =>
      expect(document.activeElement?.getAttribute("data-slot")).toBe("consent-errors"),
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the service's problem and what was recorded before it", async () => {
    const user = userEvent.setup();
    const action = vi.fn(async (): Promise<ActionState> => ({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:test",
        title: "Example problem",
        correlationId: "00000000-0000-4000-8000-000000000001",
      },
      formErrors: ["Recorded before the failure: Terms of service."],
    }));
    render(
      <ConsentForm
        action={action}
        options={OPTIONS}
        offerWhatsapp
        whatsappField="whatsapp_number"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Agree and continue" }));
    await waitFor(() => expect(screen.getByText("Example problem")).toBeDefined());
    expect(screen.getByText("Recorded before the failure: Terms of service.")).toBeDefined();
    expect(screen.getByText("00000000-0000-4000-8000-000000000001")).toBeDefined();
  });

  it("says why a CA firm has no WhatsApp box", () => {
    render(
      <ConsentForm
        action={vi.fn(async (): Promise<ActionState> => ({ status: "idle" }))}
        options={OPTIONS.filter((item) => item.purpose !== "whatsapp_reminders")}
        offerWhatsapp={false}
        whatsappField="whatsapp_number"
      />,
    );
    expect(
      screen.getByText("WhatsApp reminders are set for each client business, not for the firm."),
    ).toBeDefined();
    expect(screen.queryByRole("checkbox", { name: /whatsapp/ })).toBeNull();
  });
});
