import { REGULATORY_ROLES, TENANT_ADMIN_ROLES, TENANT_MEMBER_ROLES, hasRole } from "./roles.ts";
import type { Principal, Role } from "./roles.ts";

/**
 * Capabilities are what a screen or action asks for; the roles behind each one are the
 * authoritative matrix the docs table is generated from. Reads on /admin are open to every
 * regulatory role; writes that record a decision name the narrower set. A dry run reads every
 * tenant's profiles and the fan-out controls stop or roll back what every tenant is told, so
 * both are the admin's alone, as the engine's routes are (D-049 in docs/web/decisions.md). Every
 * regulatory role works a review task (claims, drafts, edits, returns, rejects); approving one is
 * the reviewer's or the admin's, as the role table says ("reviewer: approves and publishes"),
 * although the rulebook's shared review token lets any caller approve (D-061).
 */
export const CAPABILITIES = {
  "obligations.read": TENANT_MEMBER_ROLES,
  "obligations.update_status": TENANT_MEMBER_ROLES,
  "profile.edit": ["owner", "staff", "ca_admin", "ca_staff"],
  "consents.manage": TENANT_ADMIN_ROLES,
  "billing.manage": TENANT_ADMIN_ROLES,
  "team.manage": ["owner", "ca_admin", "admin"],
  "webhooks.manage": ["ca_admin"],
  "data_rights.manage": TENANT_ADMIN_ROLES,
  "audit.read": ["owner", "ca_admin", "compliance_lead"],
  "admin.review": REGULATORY_ROLES,
  "admin.review.approve": ["reviewer", "admin"],
  "admin.decisions.resolve": ["reviewer", "admin"],
  "admin.publish": ["reviewer", "admin"],
  "admin.entities": REGULATORY_ROLES,
  "admin.sources": REGULATORY_ROLES,
  "admin.sources.write": ["admin"],
  "admin.pipeline": REGULATORY_ROLES,
  "admin.pipeline.control": ["admin"],
  "admin.llm.read": REGULATORY_ROLES,
  "admin.tenants.read": ["admin"],
  "admin.impact": ["admin"],
  "admin.fan_outs.control": ["admin"],
  "admin.notifications.read": ["analyst", "admin"],
  "admin.notifications.resend": ["admin"],
  "admin.audit.read": REGULATORY_ROLES,
  "admin.flags.read": REGULATORY_ROLES,
  "admin.ontology": REGULATORY_ROLES,
  "admin.evals.read": REGULATORY_ROLES,
} as const satisfies Record<string, readonly Role[]>;

export type Capability = keyof typeof CAPABILITIES;

export const CAPABILITY_NAMES = Object.keys(CAPABILITIES) as readonly Capability[];

export function rolesFor(capability: Capability): readonly Role[] {
  return CAPABILITIES[capability];
}

/** True when the session holds a role the capability is granted to; anonymous is never allowed. */
export function can(principal: Principal | null, capability: Capability): boolean {
  return hasRole(principal, CAPABILITIES[capability]);
}
