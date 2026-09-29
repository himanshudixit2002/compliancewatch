import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { signInFormOptions } from "../model/sign-in";
import { DevSignInForm } from "./dev-sign-in-form";
import type { SignInAction } from "./dev-sign-in-form";

const idle: SignInAction = () => Promise.resolve({ status: "idle" });
const options = signInFormOptions();

function deferred() {
  let resolve: (state: ActionState) => void = () => {};
  const promise = new Promise<ActionState>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("DevSignInForm", () => {
  it("renders the kinds, the roles of the chosen kind, the name and tenant fields", async () => {
    const { container } = render(<DevSignInForm action={idle} options={options} next="/account" />);
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeDefined();
    const kind = screen.getByLabelText("Tenant kind") as HTMLSelectElement;
    expect(kind.value).toBe("business");
    expect(screen.getAllByRole("checkbox").map((box) => box.getAttribute("value"))).toEqual([
      "owner",
      "staff",
      "compliance_lead",
    ]);
    expect(screen.getByRole("checkbox", { name: "Owner" })).toBeDefined();
    expect(screen.getByLabelText("Display name")).toBeDefined();
    expect(screen.getByLabelText("Tenant id")).toBeDefined();
    expect(container.querySelector("input[name='next']")?.getAttribute("value")).toBe("/account");
    expect(screen.queryByRole("button", { name: "Use the last seeded tenant" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("swaps the roles when the tenant kind changes", async () => {
    render(<DevSignInForm action={idle} options={options} />);
    await userEvent.selectOptions(screen.getByLabelText("Tenant kind"), "internal");
    expect(screen.getAllByRole("checkbox").map((box) => box.getAttribute("value"))).toEqual([
      "analyst",
      "reviewer",
      "admin",
    ]);
    await userEvent.selectOptions(screen.getByLabelText("Tenant kind"), "ca_firm");
    expect(screen.getByRole("checkbox", { name: "CA admin" })).toBeDefined();
  });

  it("fills the tenant id from the seeded tenant", async () => {
    const seeded = "00000000-0000-4000-8000-000000000002";
    render(<DevSignInForm action={idle} options={options} seededTenantId={seeded} />);
    await userEvent.click(screen.getByRole("button", { name: "Use the last seeded tenant" }));
    expect((screen.getByLabelText("Tenant id") as HTMLInputElement).value).toBe(seeded);
  });

  it("submits the form data to the action and shows the busy state meanwhile", async () => {
    const { promise, resolve } = deferred();
    const action = vi.fn<SignInAction>(() => promise);
    render(<DevSignInForm action={action} options={options} next="/businesses" />);
    await userEvent.selectOptions(screen.getByLabelText("Tenant kind"), "internal");
    await userEvent.click(screen.getByRole("checkbox", { name: "Analyst" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Admin" }));
    await userEvent.type(screen.getByLabelText("Display name"), "Example analyst");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const formData = action.mock.calls[0]?.[1] as FormData;
    expect(formData.get("tenantKind")).toBe("internal");
    expect(formData.getAll("roles")).toEqual(["analyst", "admin"]);
    expect(formData.get("displayName")).toBe("Example analyst");
    expect(formData.get("tenantId")).toBe("");
    expect(formData.get("next")).toBe("/businesses");
    const busy = await screen.findByRole("button", { name: "Signing in" });
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.hasAttribute("disabled")).toBe(true);
    resolve({ status: "idle" });
    await screen.findByRole("button", { name: "Sign in" });
  });

  it("shows field errors, form errors and the problem the action returns", async () => {
    const failing: SignInAction = () =>
      Promise.resolve({
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:web-fake-sign-in-invalid",
          title: "Check the sign-in details",
          correlationId: "",
        },
        fieldErrors: {
          roles: ["Choose at least one role."],
          displayName: ["Enter a display name."],
          tenantId: ["Enter a UUID, or leave it empty."],
          tenantKind: ["Choose a tenant kind."],
        },
        formErrors: ["The flag web.example is off."],
      });
    const { container } = render(<DevSignInForm action={failing} options={options} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Choose at least one role.")).toBeDefined();
    expect(screen.getByText("Enter a display name.")).toBeDefined();
    expect(screen.getByText("Enter a UUID, or leave it empty.")).toBeDefined();
    expect(screen.getByText("Choose a tenant kind.")).toBeDefined();
    expect(screen.getByText("The flag web.example is off.")).toBeDefined();
    expect(container.querySelector("[data-slot='error-state']")?.textContent).toContain(
      "Check the sign-in details",
    );
    expect(container.querySelector("[data-slot='correlation-id']")).toBeNull();
    const roles = container.querySelector("fieldset[data-slot='roles']");
    expect(roles?.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByLabelText("Display name").getAttribute("aria-invalid")).toBe("true");
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
