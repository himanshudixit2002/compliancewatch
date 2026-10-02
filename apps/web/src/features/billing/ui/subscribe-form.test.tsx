import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { SubscribeForm, type SubscribeResult } from "./subscribe-form";

const FIELDS = { plan: "plan_key", email: "email", name: "name" };
const PLANS = [
  {
    key: "example_monthly",
    name: "Example monthly plan",
    price: "Rs 1,499.00",
    period: "per month",
  },
  { key: "example_yearly", name: "Example yearly plan", price: "Rs 0.00", period: "per year" },
];

type Action = (
  state: ActionState<SubscribeResult>,
  formData: FormData,
) => Promise<ActionState<SubscribeResult>>;

function renderForm(action: Action) {
  return render(<SubscribeForm action={action} plans={PLANS} fields={FIELDS} />);
}

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("radio", { name: /Example yearly plan/ }));
  await user.type(screen.getByLabelText(/Billing email/), "owner@example.com");
  await user.type(screen.getByLabelText(/Billing name/), "Example Traders");
  await user.click(screen.getByRole("button", { name: "Start the subscription" }));
}

describe("SubscribeForm", () => {
  it("offers each plan with its price and asks for no payment details", async () => {
    const { container } = renderForm(vi.fn<Action>(async () => ({ status: "idle" })));
    expect(
      screen.getByRole("radio", { name: "Example monthly plan, Rs 1,499.00 per month" }),
    ).toBeDefined();
    expect(container.textContent).toContain("Payment details are never entered here");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says plainly that billing is not connected, with the reference, when the service has no provider", async () => {
    let sent: FormData | undefined;
    const { container } = renderForm(
      vi.fn<Action>(async (_state, formData) => {
        sent = formData;
        return {
          status: "error",
          problem: {
            type: "urn:compliancewatch:problem:billing-disabled",
            title: "Billing provider disabled",
            correlationId: "req-example-1",
          },
        };
      }),
    );
    await fillAndSubmit();
    await screen.findByText("Billing is not connected yet");
    const disabled = container.querySelector("[data-slot='billing-disabled']") as HTMLElement;
    expect(disabled.textContent).toContain("Billing is not connected yet");
    expect(disabled.textContent).toContain("nothing was charged");
    expect(disabled.textContent).toContain("req-example-1");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        container.querySelector("[data-slot='subscribe-result']"),
      ),
    );
    expect(Object.fromEntries(sent?.entries() ?? [])).toEqual({
      plan_key: "example_yearly",
      email: "owner@example.com",
      name: "Example Traders",
    });
    // The refused values stay in the form.
    expect((screen.getByLabelText(/Billing email/) as HTMLInputElement).value).toBe(
      "owner@example.com",
    );
    expect(screen.queryByText("Billing provider disabled")).toBeNull();
  });

  it("shows the started subscription with the checkout link, or says there is none", async () => {
    const result: SubscribeResult = {
      planName: "Example yearly plan",
      status: "Created",
      providerSubscriptionId: "sub_example_1",
      startedAt: "1 Jan 2000, 5:30 am IST",
      checkoutUrl: "https://checkout.example.com/sub_example_1",
    };
    const { container, unmount } = renderForm(
      vi.fn<Action>(async () => ({ status: "ok", value: result })),
    );
    await fillAndSubmit();
    const link = await screen.findByRole("link", { name: "Open the provider's checkout page" });
    expect(link.getAttribute("href")).toBe("https://checkout.example.com/sub_example_1");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(container.querySelector("[data-slot='subscription']")?.textContent).toContain(
      "sub_example_1",
    );
    unmount();
    renderForm(
      vi.fn<Action>(async () => ({ status: "ok", value: { ...result, checkoutUrl: null } })),
    );
    await fillAndSubmit();
    expect(await screen.findByText("The provider returned no checkout page.")).toBeDefined();
  });

  it("shows another problem as an error, field errors on their fields, and form errors", async () => {
    const { container } = renderForm(
      vi.fn<Action>(async () => ({
        status: "error",
        problem: { type: "urn:example", title: "Example problem", correlationId: "req-2" },
        fieldErrors: { plan_key: ["Example plan error."], email: ["Example email error."] },
        formErrors: ["Example form error."],
      })),
    );
    await fillAndSubmit();
    expect(await screen.findByText("Example problem")).toBeDefined();
    expect(screen.getByText("Example plan error.")).toBeDefined();
    expect(screen.getByRole("radiogroup").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Example email error.")).toBeDefined();
    expect(screen.getByText("Example form error.")).toBeDefined();
    expect(container.querySelector("[data-slot='billing-disabled']")).toBeNull();
  });

  it("leaves focus in place after a refusal on the fields alone", async () => {
    renderForm(
      vi.fn<Action>(async () => ({
        status: "error",
        fieldErrors: { name: ["Example name error."] },
      })),
    );
    await fillAndSubmit();
    await screen.findByText("Example name error.");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Start the subscription" }),
    );
  });
});
