import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { CAPABILITIES } from "./permissions";
import {
  ALLOWED_ROLES,
  MFA_REQUIRED_ROLES,
  REGULATORY_ROLES,
  ROLES,
  TENANT_ADMIN_ROLES,
  TENANT_MEMBER_ROLES,
  TENANT_KINDS,
  firstRoleFor,
} from "./roles";

/**
 * The web's role matrix is a copy of the kernel's: `domain_kernel/access.py` holds the roles
 * and the role sets every service enforces, and identity's `domain/tenancy.py` the roles each
 * tenant kind allows and the first user's role. These tests parse the Python sources, so a
 * role added or moved on one side fails here until the other follows.
 */
const REPO = resolve(__dirname, "../../../../..");
const ACCESS = readFileSync(
  resolve(REPO, "packages/domain-kernel/src/domain_kernel/access.py"),
  "utf8",
);
const TENANCY = readFileSync(
  resolve(REPO, "services/identity/src/identity/domain/tenancy.py"),
  "utf8",
);

/** The values of a StrEnum: `NAME = "value"` lines between the class line and the next class. */
function enumValues(source: string, name: string): string[] {
  const start = source.indexOf(`class ${name}(StrEnum):`);
  expect(start, name).toBeGreaterThan(-1);
  const end = source.indexOf("\nclass ", start + 1);
  const body = source.slice(start, end === -1 ? undefined : end);
  return [...body.matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"$/gm)].map((match) => match[1] as string);
}

/** The role names of `NAME: Final = frozenset({Role.A, Role.B})`. */
function roleSet(source: string, name: string): string[] {
  const match = new RegExp(`${name}: Final = frozenset\\(\\s*\\{([^}]*)\\}\\s*\\)`, "s").exec(
    source,
  );
  expect(match, name).not.toBeNull();
  return [...(match?.[1] ?? "").matchAll(/Role\.([A-Z_]+)/g)]
    .map((found) => (found[1] as string).toLowerCase())
    .sort();
}

/** The `TenantKind.X: frozenset({Role...})` entries of a mapping. */
function rolesByKind(source: string, name: string): Record<string, string[]> {
  const start = source.indexOf(
    `${name}: Final[Mapping[TenantKind, frozenset[Role]]] = MappingProxyType(`,
  );
  expect(start, name).toBeGreaterThan(-1);
  const body = source.slice(start, source.indexOf("\n)\n", start));
  const result: Record<string, string[]> = {};
  for (const entry of body.matchAll(/TenantKind\.([A-Z_]+): frozenset\(\{([^}]*)\}\)/g)) {
    result[(entry[1] as string).toLowerCase()] = [
      ...(entry[2] as string).matchAll(/Role\.([A-Z_]+)/g),
    ]
      .map((found) => (found[1] as string).toLowerCase())
      .sort();
  }
  return result;
}

function firstRoles(source: string): Record<string, string> {
  const start = source.indexOf("FIRST_ROLE: Final[Mapping[TenantKind, Role]] = MappingProxyType(");
  expect(start).toBeGreaterThan(-1);
  const body = source.slice(start, source.indexOf("\n)\n", start));
  const result: Record<string, string> = {};
  for (const entry of body.matchAll(/TenantKind\.([A-Z_]+): Role\.([A-Z_]+)/g)) {
    result[(entry[1] as string).toLowerCase()] = (entry[2] as string).toLowerCase();
  }
  return result;
}

describe("the kernel's access.py", () => {
  it("names the same roles, in the same order", () => {
    expect(enumValues(ACCESS, "Role")).toEqual([...ROLES]);
  });

  it("holds the same role sets", () => {
    expect(roleSet(ACCESS, "TENANT_MEMBER_ROLES")).toEqual([...TENANT_MEMBER_ROLES].sort());
    expect(roleSet(ACCESS, "TENANT_ADMIN_ROLES")).toEqual([...TENANT_ADMIN_ROLES].sort());
    expect(roleSet(ACCESS, "REGULATORY_ROLES")).toEqual([...REGULATORY_ROLES].sort());
    expect(roleSet(ACCESS, "MFA_REQUIRED_ROLES")).toEqual([...MFA_REQUIRED_ROLES].sort());
  });
});

describe("identity's tenancy.py", () => {
  it("names the same tenant kinds and allows the same roles in each", () => {
    expect(enumValues(TENANCY, "TenantKind")).toEqual([...TENANT_KINDS]);
    const allowed = rolesByKind(TENANCY, "ALLOWED_ROLES");
    for (const kind of TENANT_KINDS) {
      expect(allowed[kind], kind).toEqual([...ALLOWED_ROLES[kind]].sort());
    }
  });

  it("gives a new tenant's first user the same role", () => {
    const first = firstRoles(TENANCY);
    for (const kind of TENANT_KINDS) expect(first[kind], kind).toBe(firstRoleFor(kind));
  });
});

describe("the capability matrix", () => {
  it("grants only roles the kernel knows", () => {
    for (const [capability, roles] of Object.entries(CAPABILITIES)) {
      for (const role of roles) expect(ROLES, `${capability}: ${role}`).toContain(role);
    }
  });

  it("gives team management to the tenant admins and the internal admin, as identity does", () => {
    expect([...CAPABILITIES["team.manage"]].sort()).toEqual(
      [...roleSet(ACCESS, "TENANT_ADMIN_ROLES"), "admin"].sort(),
    );
  });
});
