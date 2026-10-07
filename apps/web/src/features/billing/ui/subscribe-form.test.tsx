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
    const { idempotency_key: key, ...values } = Object.fromEntries(sent?.entries() ?? []);
    expect(values).toEqual({
      plan_key: "example_yearly",
      email: "owner@example.com",
      name: "Example Traders",
    });
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
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

  it("keeps one key across retries of the same values and mints a new one after a success or a change", async () => {
    const keys: string[] = [];
    let minted = 0;
    const answers: ActionState<SubscribeResult>[] = [
      { status: "error", problem: { type: "urn:example", title: "Example outage" } },
      { status: "error", problem: { type: "urn:example", title: "Example outage" } },
      {
        status: "ok",
        value: {
          planName: "Example yearly plan",
          status: "Created",
          providerSubscriptionId: "sub_example_2",
          startedAt: "1 Jan 2000, 5:30 am IST",
          checkoutUrl: null,
        },
      },
      { status: "error", problem: { type: "urn:example", title: "Example outage" } },
      { status: "error", problem: { type: "urn:example", title: "Example outage" } },
    ];
    const { container } = render(
      <SubscribeForm
        action={async (_state, formData) => {
          keys.push(String(formData.get("idempotency_key")));
          return answers[keys.length - 1] ?? { status: "idle" };
        }}
        plans={PLANS}
        fields={FIELDS}
        newKey={() => `example-key-${++minted}`}
      />,
    );
    const user = userEvent.setup();
    const submit = () => user.click(screen.getByRole("button", { name: "Start the subscription" }));
    // The fields remount once the answer renders, with the values that were sent; typing before
    // that lands in the fields the answer replaces, so each step waits for the answer's attempt.
    const answered = (count: number) =>
      waitFor(() => {
        expect(keys).toHaveLength(count);
        expect(container.querySelector("[data-attempt]")?.getAttribute("data-attempt")).toBe(
          String(count),
        );
      });
    await fillAndSubmit(); // a failure
    await answered(1);
    await submit(); // the same values again: a retry
    await answered(2);
    await submit(); // still the same: succeeds
    await answered(3);
    await fillAndSubmit(); // after a success: a new attempt
    await answered(4);
    await user.type(screen.getByLabelText(/Billing name/), " Two");
    await submit(); // the values changed: a new attempt
    await answered(5);
    expect(keys).toEqual([
      "example-key-1",
      "example-key-1",
      "example-key-1",
      "example-key-2",
      "example-key-3",
    ]);
  });

  it("asks for the units when the page names the field, and sends them", async () => {
    let sent: FormData | undefined;
    const { container } = render(
      <SubscribeForm
        action={async (_state, formData) => {
          sent = formData;
          return { status: "idle" };
        }}
        plans={PLANS}
        fields={{ ...FIELDS, quantity: "quantity" }}
      />,
    );
    await userEvent.setup().type(screen.getByLabelText(/Units/), "3");
    await fillAndSubmit();
    await waitFor(() => expect(sent?.get("quantity")).toBe("3"));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
