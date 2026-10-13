import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { MfaView, type MfaAction, type MfaViewProps } from "./mfa-view";

const fields = { code: "code", factorId: "factorId", friendlyName: "friendlyName", next: "next" };
const idle: MfaAction = () => Promise.resolve({ status: "idle" });

function view(overrides: Partial<MfaViewProps> = {}) {
  return (
    <MfaView
      mode="totp"
      who="session"
      required={false}
      verified={false}
      requiringRoles={["Analyst", "Reviewer", "Admin", "CA admin"]}
      factors={[]}
      verify={idle}
      enrol={idle}
      remove={idle}
      fields={fields}
      signInHref="/sign-in"
      accountHref="/account"
      codeLength={6}
      {...overrides}
    />
  );
}

describe("MfaView", () => {
  it("tells nobody to sign in first", async () => {
    const { container } = render(view({ who: "anonymous" }));
    expect(screen.getByRole("heading", { level: 1, name: "Two-step verification" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe("/sign-in");
    expect(container.querySelector("form")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("confirms with one button for the fake adapter, saying why and that nothing is verified", async () => {
    const verify = vi.fn<MfaAction>(() => Promise.resolve({ status: "idle" }));
    const user = userEvent.setup();
    const { container } = render(
      view({ mode: "confirm", who: "pending", required: true, verify, next: "/admin" }),
    );
    expect(screen.getByText(/Analyst, Reviewer, Admin, CA admin/)).toBeDefined();
    expect(screen.getByText("Development sign-in: nothing is verified")).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Confirm second factor" }));
    await waitFor(() => expect(verify).toHaveBeenCalledTimes(1));
    expect((verify.mock.calls[0]?.[1] as FormData).get("next")).toBe("/admin");
    expect(screen.queryByRole("link", { name: "Back to your account" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("enrols an authenticator app: the QR code and secret, then the code", async () => {
    const enrol = vi.fn<MfaAction>(() =>
      Promise.resolve({
        status: "ok",
        value: {
          enrolment: {
            factorId: "f1",
            qrSvg: "<svg xmlns='http://www.w3.org/2000/svg'/>",
            secret: "JBSWY3DPEHPK3PXP",
          },
        },
      }),
    );
    const verify = vi.fn<MfaAction>(() =>
      Promise.resolve({ status: "error", fieldErrors: { code: ["Check the code."] } }),
    );
    const user = userEvent.setup();
    const { container } = render(view({ enrol, verify }));
    expect(screen.getByText(/Your roles do not require one/)).toBeDefined();
    await user.type(screen.getByLabelText(/Name for this app/), "Work phone");
    await user.click(screen.getByRole("button", { name: "Set up an authenticator app" }));
    await waitFor(() =>
      expect(screen.getByRole("img", { name: "QR code for the authenticator app" })).toBeDefined(),
    );
    expect((enrol.mock.calls[0]?.[1] as FormData).get("friendlyName")).toBe("Work phone");
    expect(
      screen.getByRole("img", { name: "QR code for the authenticator app" }).getAttribute("src"),
    ).toMatch(/^data:image\/svg\+xml;base64,/);
    expect(container.querySelector("[data-slot='mfa-secret']")?.textContent).toBe(
      "JBSWY3DPEHPK3PXP",
    );
    await user.type(screen.getByLabelText(/Code from the app/), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(screen.getByText("Check the code.")).toBeDefined());
    const sent = verify.mock.calls[0]?.[1] as FormData;
    expect(sent.get("factorId")).toBe("f1");
    expect(sent.get("code")).toBe("123456");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("challenges a person with a factor, and lists it with removal once verified", async () => {
    const factors = [{ id: "f1", status: "verified" as const, friendlyName: "Work phone" }];
    const { container, rerender } = render(view({ factors, required: true }));
    expect(container.querySelector("[data-slot='mfa-challenge']")).not.toBeNull();
    expect(container.querySelector("input[name='factorId']")?.getAttribute("value")).toBe("f1");
    rerender(view({ factors, verified: true }));
    expect(container.querySelector("[data-slot='mfa-managed']")).not.toBeNull();
    expect(screen.getByText("Work phone")).toBeDefined();
    expect(screen.getByRole("button", { name: "Remove this app" })).toBeDefined();
    expect(screen.getByText("This session was signed in with a second factor.")).toBeDefined();
    expect(screen.getByRole("link", { name: "Back to your account" }).getAttribute("href")).toBe(
      "/account",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
