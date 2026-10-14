import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { SignInForm, type SignInStepAction, type SignInStepView } from "./sign-in-form";

const fields = { phone: "phone", code: "code", email: "email", next: "next" };
const links = [
  { method: "email" as const, href: "/sign-in?method=email", label: "Sign in with an email link" },
  { method: "dev" as const, href: "/sign-in?method=dev", label: "Development sign-in" },
];
const idle: SignInStepAction = () => Promise.resolve({ status: "idle" });

function form(overrides: Partial<Parameters<typeof SignInForm>[0]> = {}) {
  return (
    <SignInForm
      method="phone"
      startPhone={idle}
      verifyCode={idle}
      sendEmail={idle}
      fields={fields}
      otherMethods={links}
      resendAfterSeconds={30}
      codeLength={6}
      {...overrides}
    />
  );
}

describe("SignInForm", () => {
  it("starts on the phone step with the notice, the hidden next and the other methods", async () => {
    const { container } = render(form({ next: "/account", notice: "Your session ended." }));
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeDefined();
    expect(screen.getByText("Your session ended.")).toBeDefined();
    expect(screen.getByLabelText(/Mobile number/)).toBeDefined();
    expect(container.querySelector("input[name='next']")?.getAttribute("value")).toBe("/account");
    expect(
      screen.getByRole("link", { name: "Sign in with an email link" }).getAttribute("href"),
    ).toBe("/sign-in?method=email");
    expect(container.querySelector("[data-slot='sign-in']")?.getAttribute("data-step")).toBe(
      "phone",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("moves to the code step when the action says so, and offers another code after the wait", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const startPhone = vi.fn<SignInStepAction>(() =>
        Promise.resolve({ status: "ok", value: { step: "code", phone: "+919876543210" } }),
      );
      const verifyCode = vi.fn<SignInStepAction>(() =>
        Promise.resolve({
          status: "error",
          fieldErrors: { code: ["Enter the 6 digits of the code."] },
        }),
      );
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const { container } = render(form({ startPhone, verifyCode }));
      await user.type(screen.getByLabelText(/Mobile number/), "9876543210");
      await user.click(screen.getByRole("button", { name: "Send code" }));
      await waitFor(() => expect(screen.getByLabelText(/^Code/)).toBeDefined());
      expect(container.querySelector("[data-slot='code-sent-to']")?.textContent).toContain(
        "+919876543210",
      );
      const sent = startPhone.mock.calls[0]?.[1] as FormData;
      expect(sent.get("phone")).toBe("9876543210");
      const resend = screen.getByRole("button", { name: /Send another code/ }) as HTMLButtonElement;
      expect(resend.disabled).toBe(true);
      expect(resend.textContent).toMatch(/in \d+ s/);
      await vi.advanceTimersByTimeAsync(31_000);
      await waitFor(() =>
        expect(
          (screen.getByRole("button", { name: "Send another code" }) as HTMLButtonElement).disabled,
        ).toBe(false),
      );
      await user.type(screen.getByLabelText(/^Code/), "12");
      await user.click(screen.getByRole("button", { name: "Verify" }));
      await waitFor(() =>
        expect(screen.getByText("Enter the 6 digits of the code.")).toBeDefined(),
      );
      await waitFor(() =>
        expect(document.activeElement?.getAttribute("data-slot")).toBe("sign-in-errors"),
      );
      const verified = verifyCode.mock.calls[0]?.[1] as FormData;
      expect(verified.get("phone")).toBe("+919876543210");
      expect(verified.get("code")).toBe("12");
      expect(screen.getByRole("link", { name: "Use another number" })).toBeDefined();
      expect(await runAxe(container)).toHaveNoViolations();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the email step with its own action and the problem a provider answers", async () => {
    const sendEmail = vi.fn<SignInStepAction>(() =>
      Promise.resolve({
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:web-provider-rate-limited",
          title: "Too many attempts",
          detail: "Wait a minute.",
          correlationId: "",
        },
      } satisfies ActionState<SignInStepView>),
    );
    const user = userEvent.setup();
    const { container } = render(form({ method: "email", sendEmail, devNotice: true }));
    expect(screen.getByText(/any six digits pass/)).toBeDefined();
    await user.type(screen.getByLabelText(/Email address/), "owner@example.test");
    await user.click(screen.getByRole("button", { name: "Send link" }));
    await waitFor(() => expect(screen.getByText("Too many attempts")).toBeDefined());
    expect(screen.getByText("Wait a minute.")).toBeDefined();
    expect((sendEmail.mock.calls[0]?.[1] as FormData).get("email")).toBe("owner@example.test");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
