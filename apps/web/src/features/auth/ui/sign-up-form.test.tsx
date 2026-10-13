import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { SignUpForm, type SignUpAction } from "./sign-up-form";

const fields = { kind: "kind", name: "name", displayName: "displayName" };
const kinds = [
  {
    value: "business",
    label: "Business",
    description: "A business that files its own returns.",
    needsMfa: false,
  },
  {
    value: "ca_firm",
    label: "CA firm",
    description: "A firm that handles compliance for its clients.",
    needsMfa: true,
  },
];

describe("SignUpForm", () => {
  it("offers the kinds, says which needs a second factor, and submits what was typed", async () => {
    const action = vi.fn<SignUpAction>(() => Promise.resolve({ status: "idle" }));
    const user = userEvent.setup();
    const { container } = render(
      <SignUpForm action={action} fields={fields} kinds={kinds} contact="+919876543210" />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Create your account" })).toBeDefined();
    expect(screen.getByText(/\+919876543210/)).toBeDefined();
    expect(screen.getByRole("radio", { name: /Business/ })).toBeDefined();
    expect(screen.getByText(/second factor, which is set up next/)).toBeDefined();
    await user.click(screen.getByRole("radio", { name: /CA firm/ }));
    await user.type(screen.getByLabelText(/Name of the business or firm/), "Example CA");
    await user.type(screen.getByLabelText(/^Your name/), "Example admin");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const sent = action.mock.calls[0]?.[1] as FormData;
    expect(sent.get("kind")).toBe("ca_firm");
    expect(sent.get("name")).toBe("Example CA");
    expect(sent.get("displayName")).toBe("Example admin");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("keeps the values after a refused submit and focuses the errors", async () => {
    const action = vi.fn<SignUpAction>(() =>
      Promise.resolve({ status: "error", fieldErrors: { name: ["Enter a name."] } }),
    );
    const user = userEvent.setup();
    const { container } = render(
      <SignUpForm action={action} fields={fields} kinds={kinds} contact="owner@example.test" />,
    );
    await user.click(screen.getByRole("radio", { name: /CA firm/ }));
    await user.type(screen.getByLabelText(/^Your name/), "Example admin");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(screen.getByText("Enter a name.")).toBeDefined());
    await waitFor(() =>
      expect(document.activeElement?.getAttribute("data-slot")).toBe("sign-up-errors"),
    );
    expect(
      (screen.getByRole("radio", { name: /CA firm/ }) as HTMLButtonElement).getAttribute(
        "data-state",
      ),
    ).toBe("checked");
    expect((screen.getByLabelText(/^Your name/) as HTMLInputElement).value).toBe("Example admin");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
