import { describe, expect, it } from "vitest";
import { ROLES } from "@/shared/config/roles";
import { isMessageKey } from "@/shared/i18n";
import {
  ROLE_LABEL,
  ROLE_TONE,
  STATUS_LABEL,
  adminMemberFromDto,
  adminTeamSummary,
  heldRoles,
} from "./admin-team";
import type { AdminMember, UserDto } from "./admin-team";

const DTO: UserDto = {
  id: "u1",
  tenant_id: "t-internal",
  display_name: "Meera Iyer",
  email: "meera@example.com",
  phone: "+919800000002",
  roles: ["admin", "reviewer"],
  status: "active",
  session_version: 3,
  created_at: "2026-02-01T05:00:00Z",
  updated_at: "2026-02-02T05:00:00Z",
};

function member(
  id: string,
  roles: AdminMember["roles"],
  status: AdminMember["status"],
): AdminMember {
  return { id, name: id, email: `${id}@example.com`, roles, status, joinedAt: "2026-01-01" };
}

describe("adminMemberFromDto", () => {
  it("keeps what the table shows", () => {
    expect(adminMemberFromDto(DTO)).toEqual({
      id: "u1",
      name: "Meera Iyer",
      email: "meera@example.com",
      roles: ["admin", "reviewer"],
      status: "active",
      joinedAt: "2026-02-01T05:00:00Z",
    });
  });
});

describe("wording maps", () => {
  it("label and colour every role and status", () => {
    for (const role of ROLES) {
      expect(isMessageKey(ROLE_LABEL[role])).toBe(true);
      expect(ROLE_TONE[role]).toBeDefined();
    }
    expect(isMessageKey(STATUS_LABEL.active)).toBe(true);
    expect(isMessageKey(STATUS_LABEL.disabled)).toBe(true);
  });
});

describe("adminTeamSummary", () => {
  it("counts users, active, disabled and admins", () => {
    expect(
      adminTeamSummary([
        member("a", ["admin"], "active"),
        member("b", ["analyst"], "disabled"),
        member("c", ["admin", "reviewer"], "disabled"),
      ]),
    ).toEqual({ total: 3, active: 1, disabled: 2, admins: 2 });
    expect(adminTeamSummary([])).toEqual({ total: 0, active: 0, disabled: 0, admins: 0 });
  });
});

describe("heldRoles", () => {
  it("lists each held role once, in roles.ts order", () => {
    expect(
      heldRoles([
        member("a", ["admin"], "active"),
        member("b", ["reviewer", "analyst"], "active"),
        member("c", ["admin"], "active"),
        member("d", [], "active"),
      ]),
    ).toEqual(["analyst", "reviewer", "admin"]);
  });
});
