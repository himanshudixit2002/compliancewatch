import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { InviteDialog, isSeatLimit, type TeamAction } from "./invite-dialog";

const fields = {
  screen: "screen",
  userId: "userId",
  contact: "contact",
  displayName: "displayName",
  roles: "roles",
  reason: "reason",
};
const roles = [
  { value: "owner", label: "Owner", needsMfa: false },
  { value: "staff", label: "Staff", needsMfa: false },
  { value: "compliance_lead", label: "Compliance lead", needsMfa: false },
];

describe("InviteDialog", () => {
  it("opens, offers the roles, submits the form with the screen and closes on success", async () => {
    const action = vi.fn<TeamAction>(() =>
      Promise.resolve({ status: "ok", message: "Example staff was invited." }),
    );
    const user = userEvent.setup();
    render(
      <InviteDialog
        action={action}
        screenId="owner.settings.team"
        fields={fields}
        roles={roles}
        billingHref="/settings/billing"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Invite" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Invite someone");
    await user.type(screen.getByLabelText(/Mobile number or email address/), "staff@example.test");
    await user.type(screen.getByLabelText(/^Name/), "Example staff");
    await user.click(screen.getByRole("checkbox", { name: "Staff" }));
    expect(await runAxe(dialog)).toHaveNoViolations();
    await user.click(screen.getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const sent = action.mock.calls[0]?.[1] as FormData;
    expect(sent.get("screen")).toBe("owner.settings.team");
    expect(sent.get("contact")).toBe("staff@example.test");
    expect(sent.get("displayName")).toBe("Example staff");
    expect(sent.getAll("roles")).toEqual(["staff"]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the dialog open with identity's refusal, linking to billing for the seat limit", async () => {
    const action = vi.fn<TeamAction>(() =>
      Promise.resolve({
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:identity-seat-limit-reached",
          title: "Plan seat limit reached",
          detail: "the plan allows 3 seat(s) and 3 are in use",
          correlationId: "req-1",
        },
      }),
    );
    const user = userEvent.setup();
    render(
      <InviteDialog
        action={action}
        screenId="admin.team"
        fields={fields}
        roles={roles}
        billingHref="/settings/billing"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Invite" }));
    await screen.findByRole("dialog");
    await user.type(screen.getByLabelText(/Mobile number or email address/), "9876543210");
    await user.click(screen.getByRole("checkbox", { name: "Owner" }));
    await user.click(screen.getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(screen.getByText("Plan seat limit reached")).toBeDefined());
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(
      screen.getByRole("link", { name: "See the plan and its seats" }).getAttribute("href"),
    ).toBe("/settings/billing");
    expect(isSeatLimit("urn:compliancewatch:problem:identity-seat-limit-reached")).toBe(true);
    expect(isSeatLimit("urn:compliancewatch:problem:identity-last-admin")).toBe(false);
    expect(isSeatLimit(undefined)).toBe(false);
  });

  it("shows a field error on the roles", async () => {
    const action = vi.fn<TeamAction>(() =>
      Promise.resolve({
        status: "error",
        fieldErrors: { roles: ["a business tenant has no role analyst"] },
      }),
    );
    const user = userEvent.setup();
    render(
      <InviteDialog
        action={action}
        screenId="owner.settings.team"
        fields={fields}
        roles={roles}
        billingHref={null}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Invite" }));
    await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: "Send invitation" }));
    await waitFor(() =>
      expect(screen.getByText("a business tenant has no role analyst")).toBeDefined(),
    );
  });
});
