/**
 * Roles, role sets and tenant kinds.
 *
 * Copied from the identity design (WP14: the domain_kernel Role enum, ALLOWED_ROLES by tenant
 * kind and FIRST_ROLE). packages/domain-kernel/src/domain_kernel/access.py does not exist yet;
 * once it does, a test parses it and compares these values so the two cannot drift. `partner`
 * is reserved for the partner API and is not a role until then.
 */
export const ROLES = [
  "owner",
  "staff",
  "ca_admin",
  "ca_staff",
  "compliance_lead",
  "analyst",
  "reviewer",
  "admin",
] as const;

export type Role = (typeof ROLES)[number];

export const TENANT_KINDS = ["business", "ca_firm", "internal"] as const;

export type TenantKind = (typeof TENANT_KINDS)[number];

/** Roles that act inside a business or CA-firm tenant. */
export const TENANT_MEMBER_ROLES: readonly Role[] = [
  "owner",
  "staff",
  "ca_admin",
  "ca_staff",
  "compliance_lead",
];

/** Roles that manage a tenant's users; the last one cannot be removed. */
export const TENANT_ADMIN_ROLES: readonly Role[] = ["owner", "ca_admin"];

/** Internal roles that may open /admin. */
export const REGULATORY_ROLES: readonly Role[] = ["analyst", "reviewer", "admin"];

/** Roles whose sessions need a second factor. */
export const MFA_REQUIRED_ROLES: readonly Role[] = ["analyst", "reviewer", "admin", "ca_admin"];

/** The roles a user may hold in each tenant kind. */
export const ALLOWED_ROLES: Record<TenantKind, readonly Role[]> = {
  business: ["owner", "staff", "compliance_lead"],
  ca_firm: ["ca_admin", "ca_staff", "compliance_lead"],
  internal: ["analyst", "reviewer", "admin"],
};

/** The role the first user of a new tenant receives. */
const FIRST_ROLE: Record<TenantKind, Role> = {
  business: "owner",
  ca_firm: "ca_admin",
  internal: "admin",
};

/** The minimum the gates need to know about a session; identity's SessionClaims satisfies it. */
export interface Principal {
  roles: readonly Role[];
  tenantKind?: TenantKind;
}

export function isRole(value: string): value is Role {
  return (ROLES as readonly string[]).includes(value);
}

export function isTenantKind(value: string): value is TenantKind {
  return (TENANT_KINDS as readonly string[]).includes(value);
}

export function firstRoleFor(kind: TenantKind): Role {
  return FIRST_ROLE[kind];
}

/** True when the principal holds at least one of the roles. */
export function hasRole(principal: Principal | null, roles: readonly Role[]): boolean {
  if (principal === null) return false;
  return roles.some((role) => principal.roles.includes(role));
}

export function isRegulatory(principal: Principal | null): boolean {
  return hasRole(principal, REGULATORY_ROLES);
}

export function requiresMfa(roles: readonly Role[]): boolean {
  return roles.some((role) => MFA_REQUIRED_ROLES.includes(role));
}

/** The tenant kinds whose members may hold at least one of the roles. */
export function tenantKindsFor(roles: readonly Role[]): readonly TenantKind[] {
  return TENANT_KINDS.filter((kind) => roles.some((role) => ALLOWED_ROLES[kind].includes(role)));
}
