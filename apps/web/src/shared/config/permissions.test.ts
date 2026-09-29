import { describe, expect, it } from "vitest";
import { CAPABILITY_NAMES, can, rolesFor } from "./permissions.ts";
import { ROLES, isRole } from "./roles.ts";

describe("permissions", () => {
  it("grants every capability to at least one valid role", () => {
    for (const name of CAPABILITY_NAMES) {
      const roles = rolesFor(name);
      expect(roles.length, name).toBeGreaterThan(0);
      expect(roles.every(isRole), name).toBe(true);
    }
  });

  it("keeps the decision capabilities narrower than the reads", () => {
    expect(rolesFor("admin.publish")).toEqual(["reviewer", "admin"]);
    expect(rolesFor("admin.notifications.resend")).toEqual(["admin"]);
    expect(rolesFor("admin.tenants.read")).toEqual(["admin"]);
    expect(rolesFor("admin.review")).toEqual(["analyst", "reviewer", "admin"]);
    expect(rolesFor("team.manage")).toEqual(["owner", "ca_admin", "admin"]);
  });

  it("answers can() for every capability and role from the matrix", () => {
    for (const name of CAPABILITY_NAMES) {
      for (const role of ROLES) {
        expect(can({ roles: [role] }, name), `${name} x ${role}`).toBe(
          rolesFor(name).includes(role),
        );
      }
    }
    expect(can(null, "obligations.read")).toBe(false);
    expect(can({ roles: ["staff", "owner"] }, "consents.manage")).toBe(true);
  });
});
