import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { BusinessForm, type BusinessFormResult } from "./business-form";

const FIELDS = { gstin: "gstin", name: "name", registrationName: "registration_name" };
const KEY_INPUT = (
  <input type="hidden" name="idempotency_key" value="00000000-0000-4000-8000-00000000abcd" />
);

const RESULT: BusinessFormResult = {
  businessId: "00000000-0000-4000-8000-0000000000e1",
  businessName: "Example business",
  pan: "ABCDE1234F",
  gstin: "29ABCDE1234F1Z5",
  created: true,
  lookedUp: true,
  rows: [{ key: "legalName", label: "Legal name", value: "Example Legal Name Limited" }],
  applied: ["Registration type"],
  reviewTaskId: null,
  progressText: "5 of 17 answered",
  complete: false,
  nextHref: "/onboarding/00000000-0000-4000-8000-0000000000e1/questions",
};

type State = ActionState<BusinessFormResult>;

describe("BusinessForm", () => {
  it("asks for the GSTIN, the name and an optional registration name", async () => {
    const { container } = render(
      <BusinessForm
        action={vi.fn(async (): Promise<State> => ({ status: "idle" }))}
        idempotencyInput={KEY_INPUT}
        fields={FIELDS}
        againHref="/onboarding/business"
      />,
    );
    const gstin = screen.getByRole("textbox", { name: /GSTIN/ });
    expect(gstin.getAttribute("name")).toBe("gstin");
    expect(gstin.getAttribute("aria-required")).toBe("true");
    expect(screen.getByText(/knows only the demo GSTIN 29ABCDE1234F1Z5/)).toBeDefined();
    expect(screen.getByRole("textbox", { name: /Business name/ }).getAttribute("name")).toBe(
      "name",
    );
    expect(
      screen
        .getByRole("textbox", { name: /Registration name \(optional\)/ })
        .getAttribute("aria-required"),
    ).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("sends the key with the fields and keeps what was typed after a refusal", async () => {
    const user = userEvent.setup();
    let submitted: FormData | undefined;
    const action = vi.fn(async (_state: State, formData: FormData): Promise<State> => {
      submitted = formData;
      return { status: "error", fieldErrors: { gstin: ["Example GSTIN message."] } };
    });
    const { container } = render(
      <BusinessForm
        action={action}
        idempotencyInput={KEY_INPUT}
        fields={FIELDS}
        againHref="/onboarding/business"
      />,
    );
    await user.type(screen.getByRole("textbox", { name: /GSTIN/ }), "29ABC");
    await user.type(screen.getByRole("textbox", { name: /Business name/ }), "Example business");
    await user.click(screen.getByRole("button", { name: "Add the business" }));
    await waitFor(() => expect(screen.getByText("Example GSTIN message.")).toBeDefined());
    expect(submitted?.get("idempotency_key")).toBe("00000000-0000-4000-8000-00000000abcd");
    expect(submitted?.get("gstin")).toBe("29ABC");
    const gstin = screen.getByRole("textbox", { name: /GSTIN/ }) as HTMLInputElement;
    expect(gstin.value).toBe("29ABC");
    expect(gstin.getAttribute("aria-invalid")).toBe("true");
    expect((screen.getByRole("textbox", { name: /Business name/ }) as HTMLInputElement).value).toBe(
      "Example business",
    );
    expect(screen.getByText("Check the fields marked below.")).toBeDefined();
    expect(document.activeElement?.getAttribute("data-slot")).toBe("business-errors");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the service's problem with its correlation id", async () => {
    const user = userEvent.setup();
    render(
      <BusinessForm
        action={async (): Promise<State> => ({
          status: "error",
          problem: {
            type: "urn:compliancewatch:problem:test",
            title: "Example problem title",
            detail: "Example detail.",
            correlationId: "req-example-1",
          },
        })}
        idempotencyInput={KEY_INPUT}
        fields={FIELDS}
        againHref="/onboarding/business"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Add the business" }));
    await waitFor(() => expect(screen.getByText("Example problem title")).toBeDefined());
    expect(screen.getByText("req-example-1")).toBeDefined();
  });

  it("replaces the form with the result and the way on", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <BusinessForm
        action={async (): Promise<State> => ({ status: "ok", value: RESULT })}
        idempotencyInput={KEY_INPUT}
        fields={FIELDS}
        againHref="/onboarding/business"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Add the business" }));
    const heading = await screen.findByRole("heading", { name: "Example business is added" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(
      screen.getByRole("link", { name: "Continue to the questions" }).getAttribute("href"),
    ).toBe(RESULT.nextHref);
    expect(screen.getByRole("link", { name: "Add another business" }).getAttribute("href")).toBe(
      "/onboarding/business",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("points at the summary when nothing is left to ask", async () => {
    const user = userEvent.setup();
    render(
      <BusinessForm
        action={async (): Promise<State> => ({
          status: "ok",
          value: { ...RESULT, complete: true, nextHref: "/onboarding/x/done" },
        })}
        idempotencyInput={KEY_INPUT}
        fields={FIELDS}
        againHref="/onboarding/business"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Add the business" }));
    expect(
      (await screen.findByRole("link", { name: "See the summary" })).getAttribute("href"),
    ).toBe("/onboarding/x/done");
  });
});
