import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { REGISTRATION_FIELDS } from "../model/registration-form";
import { RegistrationForm, type RegistrationFormResult } from "./registration-form";

const BUSINESS_ID = "00000000-0000-4000-8000-0000000000e1";
const KEY = "00000000-0000-4000-8000-00000000abcd";

const RESULT: RegistrationFormResult = {
  registrationId: "00000000-0000-4000-8000-0000000000a2",
  gstin: "27ABCDE1234F1Z5",
  name: "Example business",
  created: true,
  lookedUp: false,
  applied: [],
  attributesHref: "/b/x/attributes?node=00000000-0000-4000-8000-0000000000a2",
  reviewTasksHref: "/b/x/review-tasks",
};

function renderForm(
  action: (
    state: ActionState<RegistrationFormResult>,
    formData: FormData,
  ) => Promise<ActionState<RegistrationFormResult>>,
) {
  return render(
    <RegistrationForm
      action={action}
      businessId={BUSINESS_ID}
      businessName="Example business"
      pan="ABCDE1234F"
      idempotencyInput={<input type="hidden" name="idempotency_key" value={KEY} />}
      fields={REGISTRATION_FIELDS}
      againHref="/b/x/profile"
    />,
  );
}

describe("RegistrationForm", () => {
  it("sends the GSTIN with the business and the key, then shows what was added", async () => {
    const user = userEvent.setup();
    let submitted: FormData | undefined;
    const action = vi.fn(
      async (
        _state: ActionState<RegistrationFormResult>,
        formData: FormData,
      ): Promise<ActionState<RegistrationFormResult>> => {
        submitted = formData;
        return { status: "ok", value: RESULT };
      },
    );
    const { container } = renderForm(action);
    expect(await runAxe(container)).toHaveNoViolations();
    await user.type(screen.getByRole("textbox", { name: /GSTIN/ }), "27abcde1234f1z5");
    await user.click(screen.getByRole("button", { name: "Add the GSTIN" }));

    const result = await waitFor(() => {
      const found = container.querySelector("[data-slot='registration-result']");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(submitted?.get("gstin")).toBe("27abcde1234f1z5");
    expect(submitted?.get("business_id")).toBe(BUSINESS_ID);
    expect(submitted?.get("idempotency_key")).toBe(KEY);
    expect(result.textContent).toContain("27ABCDE1234F1Z5 is added");
    expect(result.textContent).toContain(
      "No GSTIN lookup answered for this GSTIN, so nothing was filled in; a review task was opened to verify the registration.",
    );
    expect(screen.getByRole("link", { name: "Its attributes" }).getAttribute("href")).toBe(
      RESULT.attributesHref,
    );
    expect(screen.getByRole("link", { name: "Review tasks" }).getAttribute("href")).toBe(
      "/b/x/review-tasks",
    );
    // Another GSTIN is a page load, so its form carries a new key.
    expect(screen.getByRole("link", { name: "Add another GSTIN" }).getAttribute("href")).toBe(
      "/b/x/profile",
    );
    await waitFor(() => expect(document.activeElement).toBe(result));
    expect(await runAxe(result)).toHaveNoViolations();
  });

  it("says what the lookup filled in, or that it stored nothing, and names a GSTIN already held", async () => {
    const user = userEvent.setup();
    const answers: RegistrationFormResult[] = [
      { ...RESULT, created: false, lookedUp: true, applied: ["Registration type", "State codes"] },
    ];
    const action = vi.fn(async (): Promise<ActionState<RegistrationFormResult>> => ({
      status: "ok",
      value: answers.shift() ?? { ...RESULT, lookedUp: true },
    }));
    const { container, unmount } = renderForm(action);
    await user.type(screen.getByRole("textbox", { name: /GSTIN/ }), "27ABCDE1234F1Z5");
    await user.click(screen.getByRole("button", { name: "Add the GSTIN" }));
    await waitFor(() =>
      expect(container.textContent).toContain(
        "27ABCDE1234F1Z5 was already a registration of this business",
      ),
    );
    expect(container.textContent).toContain(
      "The GSTIN lookup answered and filled in: Registration type, State codes.",
    );
    unmount();

    const second = renderForm(action);
    await user.type(screen.getByRole("textbox", { name: /GSTIN/ }), "27ABCDE1234F1Z5");
    await user.click(screen.getByRole("button", { name: "Add the GSTIN" }));
    await waitFor(() =>
      expect(second.container.textContent).toContain(
        "The GSTIN lookup answered; nothing new was stored.",
      ),
    );
  });

  it("keeps what was typed and shows the field error, the refusal and the service's problem", async () => {
    const user = userEvent.setup();
    const answers: ActionState<RegistrationFormResult>[] = [
      {
        status: "error",
        fieldErrors: { gstin: ["Example field error."] },
      },
      {
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:test",
          title: "Example problem",
          correlationId: "00000000-0000-4000-8000-000000000001",
        },
        formErrors: ["Example refusal."],
      },
    ];
    const action = vi.fn(
      async (): Promise<ActionState<RegistrationFormResult>> =>
        answers.shift() ?? { status: "idle" },
    );
    renderForm(action);
    await user.type(screen.getByRole("textbox", { name: /GSTIN/ }), "27ABCDE9999F1Z5");
    await user.type(screen.getByRole("textbox", { name: /Registration name/ }), "Example branch");
    await user.click(screen.getByRole("button", { name: "Add the GSTIN" }));
    await waitFor(() => expect(screen.getByText("Example field error.")).toBeDefined());
    const gstin = screen.getByRole("textbox", { name: /GSTIN/ });
    expect((gstin as HTMLInputElement).value).toBe("27ABCDE9999F1Z5");
    expect(gstin.getAttribute("aria-invalid")).toBe("true");
    expect(
      (screen.getByRole("textbox", { name: /Registration name/ }) as HTMLInputElement).value,
    ).toBe("Example branch");

    await user.click(screen.getByRole("button", { name: "Add the GSTIN" }));
    await waitFor(() => expect(screen.getByText("Example problem")).toBeDefined());
    expect(screen.getByText("Example refusal.")).toBeDefined();
    expect(screen.getByText("The GSTIN was not added")).toBeDefined();
  });
});
