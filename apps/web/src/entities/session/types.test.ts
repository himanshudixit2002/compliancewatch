import { describe, expect, expectTypeOf, it } from "vitest";
import { ROLES, TENANT_KINDS } from "@/shared/config/roles";
import type { Role, TenantKind } from "@/shared/config/roles";
import { SESSION_COOKIE_NAME, SESSION_PROVIDERS } from "./types";
import type { SessionRole, SessionTenantKind } from "./types";

describe("session types", () => {
  it("name exactly the roles and tenant kinds of shared/config/roles.ts", () => {
    // Compile-time: a role added to one list and not the other fails `tsc`.
    expectTypeOf<SessionRole>().toEqualTypeOf<Role>();
    expectTypeOf<SessionTenantKind>().toEqualTypeOf<TenantKind>();
    const roles: readonly SessionRole[] = ROLES;
    const kinds: readonly SessionTenantKind[] = TENANT_KINDS;
    expect(roles).toHaveLength(8);
    expect(kinds).toEqual(["business", "ca_firm", "internal"]);
  });

  it("fix the cookie name and the provider names", () => {
    expect(SESSION_COOKIE_NAME).toBe("cw_session");
    expect(SESSION_PROVIDERS).toEqual(["fake", "supabase"]);
  });
});
