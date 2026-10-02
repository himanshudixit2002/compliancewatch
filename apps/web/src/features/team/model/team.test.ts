import { describe, expect, it } from "vitest";
import { ROLES } from "@/shared/config/roles";
import { isMessageKey } from "@/shared/i18n";
import { ROLE_LABEL, ROLE_TONE, sortMembers, teamMemberFromDto, teamSummary } from "./team";
import type { TeamMember, UserDto } from "./team";

const DTO: UserDto = {
  id: "u1",
  tenant_id: "t1",
  display_name: "Asha Rao",
  email: "asha@example.com",
  phone: "+919800000001",
  roles: ["owner"],
  status: "active",
  session_version: 1,
  created_at: "2026-04-10T05:00:00Z",
  updated_at: "2026-04-11T05:00:00Z",
};

function member(id: string, name: string, status: TeamMember["status"]): TeamMember {
  return { id, name, email: `${id}@example.com`, roles: ["staff"], status, joinedAt: "2026-01-01" };
}

describe("teamMemberFromDto", () => {
  it("keeps what the table shows and drops the phone and session version", () => {
    expect(teamMemberFromDto(DTO)).toEqual({
      id: "u1",
      name: "Asha Rao",
      email: "asha@example.com",
      roles: ["owner"],
      status: "active",
      joinedAt: "2026-04-10T05:00:00Z",
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
      member("c", "Chitra", "disabled"),
      member("b", "Bala", "active"),
      member("a", "Arun", "disabled"),
      member("d", "Anil", "active"),
    ];
    expect(sortMembers(input).map((m) => m.name)).toEqual(["Anil", "Bala", "Arun", "Chitra"]);
    expect(input[0]?.name).toBe("Chitra");
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
