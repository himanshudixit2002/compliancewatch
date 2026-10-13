import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { TeamAction } from "./invite-dialog";
import { MemberActions } from "./member-actions";

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
const member = { id: "u2", name: "Example staff", roles: ["staff"] };
const idle: TeamAction = () => Promise.resolve({ status: "idle" });

describe("MemberActions", () => {
  it("changes roles through its dialog with the current ones ticked", async () => {
    const changeRoles = vi.fn<TeamAction>(() => Promise.resolve({ status: "ok", message: "done" }));
    const user = userEvent.setup();
    render(
      <MemberActions
        member={member}
        screenId="owner.settings.team"
        fields={fields}
        roles={roles}
        changeRoles={changeRoles}
        disable={idle}
        isSelf={false}
        lastAdmin={false}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Change the roles of Example staff" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Roles of Example staff");
    expect(
      (screen.getByRole("checkbox", { name: "Staff" }) as HTMLButtonElement).getAttribute(
        "data-state",
      ),
    ).toBe("checked");
    await user.click(screen.getByRole("checkbox", { name: "Compliance lead" }));
    expect(await runAxe(dialog)).toHaveNoViolations();
    await user.click(screen.getByRole("button", { name: "Save roles" }));
    await waitFor(() => expect(changeRoles).toHaveBeenCalledTimes(1));
    const sent = changeRoles.mock.calls[0]?.[1] as FormData;
    expect(sent.get("userId")).toBe("u2");
    expect(sent.getAll("roles")).toEqual(["staff", "compliance_lead"]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the roles dialog open with the last-admin refusal", async () => {
    const changeRoles = vi.fn<TeamAction>(() =>
      Promise.resolve({
        status: "error",
        formErrors: ["This is the account's only admin. Make someone else an admin first."],
      }),
    );
    const user = userEvent.setup();
    render(
      <MemberActions
        member={{ id: "u1", name: "Example owner", roles: ["owner"] }}
        screenId="owner.settings.team"
        fields={fields}
        roles={roles}
        changeRoles={changeRoles}
        disable={idle}
        isSelf
        lastAdmin
      />,
    );
    expect(screen.queryByRole("button", { name: /Disable/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Change the roles of Example owner" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("only admin");
    await user.click(screen.getByRole("button", { name: "Save roles" }));
    await waitFor(() => expect(screen.getByText(/Make someone else an admin first/)).toBeDefined());
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("disables a member with a reason of at least ten characters", async () => {
    const disable = vi.fn<TeamAction>(() => Promise.resolve({ status: "ok", message: "done" }));
    const user = userEvent.setup();
    render(
      <MemberActions
        member={member}
        screenId="admin.team"
        fields={fields}
        roles={roles}
        changeRoles={idle}
        disable={disable}
        isSelf={false}
        lastAdmin={false}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Disable Example staff" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Disable Example staff?");
    const confirm = screen.getByRole("button", { name: "Disable" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    await user.type(screen.getByLabelText(/Reason/), "Left the company in April");
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Disable" }) as HTMLButtonElement).disabled).toBe(
        false,
      ),
    );
    expect(await runAxe(dialog)).toHaveNoViolations();
    await user.click(screen.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(disable).toHaveBeenCalledTimes(1));
    const sent = disable.mock.calls[0]?.[1] as FormData;
    expect(sent.get("screen")).toBe("admin.team");
    expect(sent.get("userId")).toBe("u2");
    expect(sent.get("reason")).toBe("Left the company in April");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
