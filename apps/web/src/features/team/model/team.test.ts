import { describe, expect, it } from "vitest";
import { ROLES } from "@/shared/config/roles";
import { isMessageKey } from "@/shared/i18n";
import {
  ROLE_LABEL,
  ROLE_TONE,
  adminRolesFor,
  isLastAdmin,
  parseDisableForm,
  parseInviteForm,
  parseRolesForm,
  roleOptionsFor,
  sortMembers,
  teamMemberFromDto,
  teamSummary,
} from "./team";
import type { TeamMember, UserDto } from "./team";

const DTO: UserDto = {
  id: "u1",
  tenant_id: "t1",
  display_name: "Example owner",
  email: "owner@example.com",
  phone: "+910000000001",
  roles: ["owner"],
  status: "active",
  session_version: 1,
  created_at: "2000-04-10T05:00:00Z",
  updated_at: "2000-04-11T05:00:00Z",
};

function member(id: string, name: string, status: TeamMember["status"]): TeamMember {
  return {
    id,
    name,
    email: `${id}@example.com`,
    phone: "",
    roles: ["staff"],
    status,
    joinedAt: "2000-01-01",
  };
}

describe("teamMemberFromDto", () => {
  it("keeps what the table shows and drops the session version", () => {
    expect(teamMemberFromDto(DTO)).toEqual({
      id: "u1",
      name: "Example owner",
      email: "owner@example.com",
      phone: "+910000000001",
      roles: ["owner"],
      status: "active",
      joinedAt: "2000-04-10T05:00:00Z",
    });
  });
});

describe("role maps", () => {
  it("label and colour every role", () => {
    for (const role of ROLES) {
      expect(isMessageKey(ROLE_LABEL[role])).toBe(true);
      expect(ROLE_TONE[role]).toBeDefined();
    }
  });
});

describe("sortMembers", () => {
  it("puts active members first, then orders by name, without changing the input", () => {
    const input = [
      member("c", "Example member D", "disabled"),
      member("b", "Example member C", "active"),
      member("a", "Example member B", "disabled"),
      member("d", "Example member A", "active"),
    ];
    expect(sortMembers(input).map((m) => m.name)).toEqual([
      "Example member A",
      "Example member C",
      "Example member B",
      "Example member D",
    ]);
    expect(input[0]?.name).toBe("Example member D");
  });
});

describe("teamSummary", () => {
  it("counts members, active and disabled", () => {
    expect(
      teamSummary([
        member("a", "A", "active"),
        member("b", "B", "disabled"),
        member("c", "C", "active"),
      ]),
    ).toEqual({ total: 3, active: 2, disabled: 1 });
    expect(teamSummary([])).toEqual({ total: 0, active: 0, disabled: 0 });
  });
});

describe("management", () => {
  const data = (entries: Record<string, string | string[]>) => {
    const formData = new FormData();
    for (const [key, value] of Object.entries(entries)) {
      for (const item of Array.isArray(value) ? value : [value]) formData.append(key, item);
    }
    return formData;
  };

  it("offers each kind its roles, marking those that sign in with a second factor", () => {
    expect(roleOptionsFor("business").map((option) => option.value)).toEqual([
      "owner",
      "staff",
      "compliance_lead",
    ]);
    expect(roleOptionsFor("internal").every((option) => option.needsMfa)).toBe(true);
    expect(roleOptionsFor("ca_firm").find((option) => option.value === "ca_admin")?.needsMfa).toBe(
      true,
    );
    expect(roleOptionsFor("business").some((option) => option.needsMfa)).toBe(false);
    expect(adminRolesFor("business")).toEqual(["owner"]);
    expect(adminRolesFor("ca_firm")).toEqual(["ca_admin"]);
    expect(adminRolesFor("internal")).toEqual(["admin"]);
  });

  it("knows the only active admin", () => {
    const owner = member("u1", "Owner", "active");
    const admin: TeamMember = { ...owner, roles: ["owner"] };
    const other: TeamMember = { ...member("u2", "Other", "active"), roles: ["owner"] };
    const gone: TeamMember = { ...member("u3", "Gone", "disabled"), roles: ["owner"] };
    expect(isLastAdmin([admin, member("u4", "Staff", "active"), gone], "u1", "business")).toBe(
      true,
    );
    expect(isLastAdmin([admin, other], "u1", "business")).toBe(false);
    expect(isLastAdmin([admin], "u4", "business")).toBe(false);
  });

  it("reads the invite form: one contact, the kind's roles, the screen", () => {
    expect(
      parseInviteForm(
        data({
          screen: "owner.settings.team",
          contact: "98765 43210",
          displayName: " Example staff ",
          roles: ["staff"],
        }),
        "business",
      ),
    ).toEqual({
      ok: true,
      value: {
        screen: "owner.settings.team",
        contact: { phone: "+919876543210" },
        displayName: "Example staff",
        roles: ["staff"],
      },
    });
    const email = parseInviteForm(
      data({
        screen: "admin.team",
        contact: " Analyst@Example.test ",
        roles: ["analyst", "admin"],
      }),
      "internal",
    );
    expect(email.ok && email.value.contact).toEqual({ email: "analyst@example.test" });
    expect(email.ok && email.value.roles).toEqual(["analyst", "admin"]);
    const refused = parseInviteForm(
      data({ screen: "nope", contact: "", roles: ["analyst"] }),
      "business",
    );
    expect(refused.ok).toBe(false);
    if (!refused.ok) {
      expect(Object.keys(refused.fieldErrors).sort()).toEqual(["contact", "roles", "screen"]);
      expect(refused.fieldErrors.roles?.[0]).toContain("analyst");
    }
    expect(
      parseInviteForm(data({ screen: "admin.team", contact: "nope", roles: ["admin"] }), "internal")
        .ok,
    ).toBe(false);
    expect(
      parseInviteForm(data({ screen: "admin.team", contact: "+919876543210" }), "internal").ok,
    ).toBe(false);
  });

  it("reads the roles and disable forms", () => {
    expect(
      parseRolesForm(
        data({ screen: "admin.team", userId: " u2 ", roles: ["reviewer"] }),
        "internal",
      ),
    ).toEqual({
      ok: true,
      value: { screen: "admin.team", userId: "u2", roles: ["reviewer"] },
    });
    expect(
      parseRolesForm(data({ screen: "admin.team", userId: "", roles: [] }), "internal").ok,
    ).toBe(false);
    expect(
      parseDisableForm(
        data({ screen: "owner.settings.team", userId: "u2", reason: " Left in April 2000 " }),
      ),
    ).toEqual({
      ok: true,
      value: { screen: "owner.settings.team", userId: "u2", reason: "Left in April 2000" },
    });
    const short = parseDisableForm(
      data({ screen: "owner.settings.team", userId: "u2", reason: "short" }),
    );
    expect(short.ok).toBe(false);
    if (!short.ok) expect(short.fieldErrors.reason?.[0]).toContain("10");
  });
});
