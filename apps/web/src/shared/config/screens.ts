import type { Route } from "next";
import type { FlagName } from "./flags.ts";
import { REGULATORY_ROLES, TENANT_MEMBER_ROLES } from "./roles.ts";
import type { Role, TenantKind } from "./roles.ts";
import { SERVICES_WITH_SPECS } from "./services.ts";
import type { HttpMethod, RouteRef, ServiceName } from "./services.ts";

/**
 * The screen registry: one entry per page, route handler, embedded component or capability,
 * whether it is built or not. Navigation, breadcrumbs, the sitemap, the "not available yet"
 * pages, the generated docs and the route-coverage test all read this list, so a screen
 * exists here before anything else.
 *
 * Status rules (checked by screens.test.ts against the committed OpenAPI specs), in the order a
 * screen moves through them, planned -> waiting -> ready -> live:
 *   planned  every awaited route is unscheduled ("unplanned"); no page.tsx
 *   waiting  at least one awaited route or file is absent; no page.tsx (the catch-all serves it)
 *   ready    every awaited route and file is present and every present awaited route is also in
 *            `uses`; the screen is not built, so no page.tsx (the catch-all serves it)
 *   live     every `uses` path exists in a spec; a page has its page.tsx and e2e specs
 * A waiting entry whose awaits have all landed fails the test with "backend merged"; the change
 * that notices moves it to ready, and building the screen stays with the package that owns it.
 * A screen whose every route is already in a committed spec joins as a ready entry with its
 * routes under `uses` and nothing awaited.
 *
 * Files in this directory use explicit ".ts" relative imports and no "@/" alias so the docs
 * generator can load them under plain Node.
 */

export type ScreenKind = "page" | "handler" | "component" | "capability";
export type ScreenSection = "owner" | "ca" | "account" | "admin" | "system";
export type ScreenStatus = "live" | "ready" | "waiting" | "planned";

/** Who delivers an awaited backend: the services track, the KAG track, or nobody yet. */
export type AwaitOwner = "plan-a" | "plan-k" | "unplanned";

export interface AwaitedRoute extends RouteRef {
  owner: AwaitOwner;
  /** The delivering package (for example "WP22"), or a note on an indicative path. */
  ref?: string;
  /** The path comes from a design whose spec is not committed yet; the audit reports drift. */
  unconfirmed?: true;
  /**
   * A request header the route requires in the form the screen waits for (the Idempotency-Key of
   * a hardened route whose path is already on main). Until a committed spec declares the header
   * required on that route, the route counts as absent.
   */
  header?: string;
}

/** A repository file a screen needs (the flag registry), for the few screens without a route. */
export interface AwaitedFile {
  path: string;
  owner: AwaitOwner;
  ref?: string;
}

export interface NavPlacement {
  group: string;
  order: number;
}

export interface Screen {
  /** Dot path starting with the section: owner.obligations, admin.review, system.home. */
  id: string;
  kind: ScreenKind;
  /** The app route (Next segment syntax); for components and capabilities, the hosting route. */
  route: string;
  title: string;
  section: ScreenSection;
  roles: readonly Role[] | "public";
  tenantKinds?: readonly TenantKind[];
  flag?: FlagName;
  /** Routes the screen calls today; every one must exist in a committed spec. */
  uses: readonly RouteRef[];
  /** Routes the screen still needs. */
  awaits: readonly AwaitedRoute[];
  awaitsFiles?: readonly AwaitedFile[];
  status: ScreenStatus;
  /** A component rendered under the not-available notice (an app-supplied name). */
  preview?: string;
  /** Playwright spec files under apps/web/e2e that visit this screen. */
  e2e: readonly string[];
  guideRef: string;
  nav?: NavPlacement;
  parent?: string;
  notes?: string;
}

const MEMBERS = TENANT_MEMBER_ROLES;
const REGULATORY = REGULATORY_ROLES;
const TENANT_ADMINS: readonly Role[] = ["owner", "ca_admin"];
const CA: readonly Role[] = ["ca_admin", "ca_staff"];
/** Who onboards a business: its owner and staff, or a CA firm's people for a client. */
const ONBOARDING_ROLES: readonly Role[] = ["owner", "staff", "ca_admin", "ca_staff"];
const BUSINESS_TENANTS: readonly TenantKind[] = ["business", "ca_firm"];

const uses = (service: ServiceName, method: HttpMethod, path: string): RouteRef => ({
  service,
  method,
  path,
});

/** A route the services track delivers in the named package. */
const servicesTrack = (
  ref: string,
  service: ServiceName,
  method: HttpMethod,
  path: string,
): AwaitedRoute => ({ service, method, path, owner: "plan-a", ref });

/** A route nobody has scheduled; the path is indicative. */
const unscheduled = (
  service: ServiceName,
  method: HttpMethod,
  path: string,
  ref = "indicative path; no design exists",
): AwaitedRoute => ({ service, method, path, owner: "unplanned", ref });

const BUSINESS = uses("profile", "GET", "/v1/businesses/{business_id}");
const NODE_REVIEW_TASKS = uses("profile", "GET", "/v1/profile/nodes/{node_id}/review-tasks");
const RULE_VERSIONS = uses("rulebook", "GET", "/v1/rulebook/rule-versions");
const RULE_VERSION = uses("rulebook", "GET", "/v1/rulebook/rule-versions/{rule_version_id}");
const RELATIONS = uses("rulebook", "GET", "/v1/rulebook/relations");
const RULEBOOK_DOCUMENT = uses("rulebook", "GET", "/v1/rulebook/documents/{document_id}");
const CLAUSE = uses("rulebook", "GET", "/v1/rulebook/clauses/{clause_id}");
const ENTITY = uses("rulebook", "GET", "/v1/rulebook/entities/{entity_id}");
const REVIEW_RELATIONS = uses("rulebook", "GET", "/v1/rulebook/review/relations");
/** The public API's list of one profile node's obligations, a page at a time. */
const BUSINESS_OBLIGATIONS = uses("obligation", "GET", "/v1/businesses/{business_id}/obligations");
const CHANGES = uses("rulebook", "GET", "/v1/changes");
const CHANGE_IMPACT = uses("applicability-engine", "GET", "/v1/changes/{rule_version_id}/impact");
/** py-common's liveness and readiness routes, which every committed spec carries. */
const PROBES: readonly RouteRef[] = SERVICES_WITH_SPECS.flatMap((service) => [
  uses(service, "GET", "/health"),
  uses(service, "GET", "/ready"),
]);
const ONTOLOGY = servicesTrack("WP12", "profile", "GET", "/v1/ontology");
const RAW_DOCUMENT = servicesTrack(
  "WP18",
  "pipeline",
  "GET",
  "/v1/pipeline/documents/{document_id}/raw",
);
const UPLOADS = servicesTrack("WP19", "pipeline", "POST", "/v1/pipeline/sources/{key}/uploads");
/** An admin's upload of a document to a source, and the pipeline's task queue (M2-3). */
const UPLOAD = uses("pipeline", "POST", "/v1/pipeline/sources/{key}/uploads");
const TASKS = uses("pipeline", "GET", "/v1/pipeline/tasks");
const TASK_RESOLVE = uses("pipeline", "POST", "/v1/pipeline/tasks/{task_id}/resolve");
const TASK_DISMISS = uses("pipeline", "POST", "/v1/pipeline/tasks/{task_id}/dismiss");
/** The source manager's routes (M2-2), which the sources screens call once built. */
const SOURCE_LIST = uses("pipeline", "GET", "/v1/pipeline/sources");
const SOURCE_ADD = uses("pipeline", "POST", "/v1/pipeline/sources");
const SOURCE_EDIT = uses("pipeline", "PATCH", "/v1/pipeline/sources/{key}");
const SOURCE_FETCH = uses("pipeline", "POST", "/v1/pipeline/sources/{key}/fetch");
const SOURCE_DOCUMENTS = uses("pipeline", "GET", "/v1/pipeline/sources/{key}/documents");
const STORED_DOCUMENT = uses("pipeline", "GET", "/v1/pipeline/documents/{document_id}");
const STORED_BYTES = uses("pipeline", "GET", "/v1/pipeline/documents/{document_id}/raw");
/** The pipeline's operations (M2-7): runs, every source's documents, a retry, the dead outbox. */
const RUNS = uses("pipeline", "GET", "/v1/pipeline/runs");
const EVERY_DOCUMENT = uses("pipeline", "GET", "/v1/pipeline/documents");
const DOCUMENT_RETRY = uses("pipeline", "POST", "/v1/pipeline/documents/{document_id}/retry");
const DEAD_OUTBOX = uses("pipeline", "GET", "/v1/pipeline/outbox/dead");
const OUTBOX_REQUEUE = uses("pipeline", "POST", "/v1/pipeline/outbox/{event_id}/requeue");
const SESSION_EXCHANGE = servicesTrack("WP14", "identity", "POST", "/v1/identity/sessions");
const DEV_PROVIDER_TOKENS = servicesTrack(
  "WP14",
  "identity",
  "POST",
  "/v1/identity/dev/provider-tokens",
);
const SESSIONS = uses("identity", "POST", "/v1/identity/sessions");
const DEV_TOKENS = uses("identity", "POST", "/v1/identity/dev/provider-tokens");
const IDENTITY_USER_ROUTES: readonly RouteRef[] = [
  uses("identity", "GET", "/v1/identity/users"),
  uses("identity", "POST", "/v1/identity/users"),
  uses("identity", "PUT", "/v1/identity/users/{user_id}/roles"),
  uses("identity", "POST", "/v1/identity/users/{user_id}/disable"),
];
const IDENTITY_USERS: readonly AwaitedRoute[] = [
  servicesTrack("WP14", "identity", "GET", "/v1/identity/users"),
  servicesTrack("WP14", "identity", "POST", "/v1/identity/users"),
  servicesTrack("WP14", "identity", "PUT", "/v1/identity/users/{user_id}/roles"),
  servicesTrack("WP14", "identity", "POST", "/v1/identity/users/{user_id}/disable"),
];
const DATA_EXPORT = servicesTrack(
  "WP24",
  "identity",
  "GET",
  "/v1/identity/data-requests/{request_id}/export",
);
const NOTIFICATIONS = uses("notification", "GET", "/v1/notification/notifications");
const NOTIFICATION = uses(
  "notification",
  "GET",
  "/v1/notification/notifications/{notification_id}",
);
const BUDGET_ALARMS = servicesTrack("WP27", "eval", "GET", "/v1/eval/budget-alarms");
const QA_COVERAGE = servicesTrack("WP28", "eval", "GET", "/v1/eval/qa-coverage");
const REVIEW_STATS = servicesTrack("WP21", "rulebook", "GET", "/v1/rulebook/review/stats");
/** The rulebook's review tasks (M2-4, M2-6): the queue, the seed tasks, a task, its claim, the
 * version drafted from a candidate task's candidate, its draft's edit and its decision, and the
 * stats. */
const REVIEW_TASKS = uses("rulebook", "GET", "/v1/rulebook/review/tasks");
const REVIEW_SEED = uses("rulebook", "POST", "/v1/rulebook/review/tasks/seed");
const REVIEW_TASK = uses("rulebook", "GET", "/v1/rulebook/review/tasks/{task_id}");
const REVIEW_CLAIM = uses("rulebook", "POST", "/v1/rulebook/review/tasks/{task_id}/claim");
const REVIEW_DRAFT = uses("rulebook", "POST", "/v1/rulebook/review/tasks/{task_id}/draft");
const REVIEW_EDIT = uses("rulebook", "PATCH", "/v1/rulebook/review/tasks/{task_id}/draft");
const REVIEW_DECIDE = uses("rulebook", "POST", "/v1/rulebook/review/tasks/{task_id}/decide");
const REVIEW_STATS_READ = uses("rulebook", "GET", "/v1/rulebook/review/stats");

const SCREEN_LIST = [
  // ---- system -----------------------------------------------------------------------------
  {
    id: "system.home",
    kind: "page",
    route: "/",
    title: "Home",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["home.spec.ts", "a11y.spec.ts", "journey-visitor.spec.ts"],
    guideRef: "10, 15",
  },
  {
    id: "system.sign-in",
    kind: "page",
    route: "/sign-in",
    title: "Sign in",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [SESSION_EXCHANGE, DEV_PROVIDER_TOKENS],
    status: "live",
    e2e: ["sign-in.spec.ts", "a11y.spec.ts", "journey-visitor.spec.ts"],
    guideRef: "10, 12, 16; ADR-014",
    notes:
      "The development sign-in on the fake provider (local and test); the identity routes it awaits bring the real one.",
  },
  {
    id: "system.sign-out",
    kind: "handler",
    route: "/sign-out",
    title: "Sign out",
    section: "system",
    roles: [...MEMBERS, ...REGULATORY],
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["sign-in.spec.ts", "journey-owner.spec.ts"],
    guideRef: "16",
    notes: "POST only; clears the session cookie and returns to the sign-in page.",
  },
  {
    id: "system.sitemap",
    kind: "page",
    route: "/sitemap",
    title: "All screens",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["sitemap.spec.ts", "a11y.spec.ts"],
    guideRef: "14, 15",
  },
  {
    id: "system.design",
    kind: "page",
    route: "/design",
    title: "Design system",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["design.spec.ts", "a11y.spec.ts"],
    guideRef: "12",
    notes: "Every UI kit component with example data; a 404 unless CW_WEB_ENV is local or test.",
  },
  {
    id: "system.legal",
    kind: "page",
    route: "/legal/[doc]",
    title: "Legal document",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["legal.spec.ts", "journey-owner.spec.ts", "journey-visitor.spec.ts"],
    guideRef: "16",
    notes: "Rendered from docs/legal under the draft banner; an unknown name is a 404.",
  },
  {
    id: "system.forbidden",
    kind: "page",
    route: "/forbidden",
    title: "Forbidden",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["forbidden.spec.ts", "a11y.spec.ts"],
    guideRef: "15, 16",
    notes:
      "The redirect target of a failed role gate; public so an ended session can still read it.",
  },
  {
    id: "system.not-available",
    kind: "page",
    route: "/[...slug]",
    title: "Not available yet",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["not-available.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    notes: "Catch-all serving every tenant screen that is not built, from its registry entry.",
  },
  {
    id: "system.health",
    kind: "handler",
    route: "/api/health",
    title: "Health",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["health.spec.ts"],
    guideRef: "17",
  },
  {
    id: "system.sign-in-email-sent",
    kind: "page",
    route: "/sign-in/email-sent",
    title: "Check your email",
    section: "system",
    roles: "public",
    uses: [SESSIONS],
    awaits: [SESSION_EXCHANGE],
    status: "ready",
    e2e: [],
    guideRef: "ADR-014",
  },
  {
    id: "system.sign-up",
    kind: "page",
    route: "/sign-up",
    title: "Create your account",
    section: "system",
    roles: "public",
    uses: [uses("identity", "POST", "/v1/identity/tenants")],
    awaits: [servicesTrack("WP14", "identity", "POST", "/v1/identity/tenants")],
    status: "ready",
    e2e: [],
    guideRef: "6, 10",
  },
  {
    id: "system.auth-callback",
    kind: "handler",
    route: "/auth/callback",
    title: "Email link callback",
    section: "system",
    roles: "public",
    uses: [SESSIONS],
    awaits: [SESSION_EXCHANGE],
    status: "ready",
    e2e: [],
    guideRef: "ADR-014",
  },
  {
    id: "system.sign-in-sso",
    kind: "page",
    route: "/sign-in/sso",
    title: "Single sign-on",
    section: "system",
    roles: ["compliance_lead"],
    uses: [],
    awaits: [unscheduled("identity", "POST", "/v1/identity/sso/exchange")],
    status: "planned",
    e2e: [],
    guideRef: "10; G92",
  },
  {
    id: "system.quality",
    kind: "page",
    route: "/quality",
    title: "Quality numbers",
    section: "system",
    roles: [...MEMBERS, ...REGULATORY],
    uses: [],
    awaits: [unscheduled("eval", "GET", "/v1/eval/quality")],
    status: "planned",
    e2e: [],
    guideRef: "1 commitment 3",
  },
  {
    id: "system.hindi-ui",
    kind: "capability",
    route: "/",
    title: "Hindi interface",
    section: "system",
    roles: "public",
    uses: [],
    awaits: [],
    awaitsFiles: [
      { path: "packages/ontology/src/ontology/data/wording.hi.yaml", owner: "unplanned" },
      { path: "apps/web/src/shared/i18n/messages/hi.json", owner: "unplanned" },
    ],
    status: "planned",
    e2e: [],
    guideRef: "G54",
    notes:
      "createTranslator('hi') falls back to English key by key until the Hindi messages exist.",
  },
  {
    id: "system.raw-document",
    kind: "handler",
    route: "/api-bff/pipeline/documents/[documentId]/raw",
    title: "Raw document stream",
    section: "system",
    roles: REGULATORY,
    uses: [STORED_BYTES],
    awaits: [RAW_DOCUMENT],
    status: "ready",
    e2e: [],
    guideRef: "15",
  },
  {
    id: "system.uploads",
    kind: "handler",
    route: "/api-bff/pipeline/sources/[key]/uploads",
    title: "Document upload",
    section: "system",
    roles: REGULATORY,
    uses: [UPLOAD],
    awaits: [UPLOADS],
    status: "ready",
    e2e: [],
    guideRef: "7, 15",
  },
  {
    id: "system.data-export",
    kind: "handler",
    route: "/api-bff/data-requests/[requestId]/export",
    title: "Data export download",
    section: "system",
    roles: TENANT_ADMINS,
    uses: [],
    awaits: [DATA_EXPORT],
    status: "waiting",
    e2e: [],
    guideRef: "16",
  },
  // ---- account ----------------------------------------------------------------------------
  {
    id: "account.home",
    kind: "page",
    route: "/account",
    title: "Account",
    section: "account",
    roles: [...MEMBERS, ...REGULATORY],
    uses: [],
    awaits: [servicesTrack("WP14", "identity", "GET", "/v1/identity/me")],
    status: "live",
    e2e: ["account.spec.ts", "a11y.spec.ts"],
    guideRef: "6, 16",
    nav: { group: "account", order: 1 },
    notes:
      "The session facts and sign out; the profile fields arrive with the identity route it awaits.",
  },
  {
    id: "account.mfa",
    kind: "page",
    route: "/account/mfa",
    title: "Two-step verification",
    section: "account",
    roles: [...MEMBERS, ...REGULATORY],
    uses: [SESSIONS, DEV_TOKENS],
    awaits: [SESSION_EXCHANGE, DEV_PROVIDER_TOKENS],
    status: "ready",
    e2e: [],
    guideRef: "16, 17",
    nav: { group: "account", order: 3 },
  },
  // ---- owner ------------------------------------------------------------------------------
  {
    id: "owner.businesses",
    kind: "page",
    route: "/businesses",
    title: "Businesses",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [uses("profile", "GET", "/v1/businesses")],
    awaits: [],
    status: "live",
    e2e: ["businesses.spec.ts", "a11y.spec.ts", "journey-owner.spec.ts", "journey-ca-firm.spec.ts"],
    guideRef: "6, 10; F12",
    nav: { group: "business", order: 1 },
    notes:
      "Where every tenant role lands after signing in: an owner with one business goes straight to it (whose home links to adding another); a CA firm's client list with search and paging.",
  },
  {
    id: "owner.onboarding",
    kind: "page",
    route: "/onboarding",
    title: "Get started",
    section: "owner",
    roles: ONBOARDING_ROLES,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      uses("identity", "GET", "/v1/identity/consents"),
      uses("identity", "POST", "/v1/identity/consents"),
      uses("notification", "PUT", "/v1/notification/preferences/{channel}/{recipient}"),
    ],
    awaits: [],
    status: "live",
    e2e: [
      "owner-onboarding.spec.ts",
      "a11y.spec.ts",
      "journey-owner.spec.ts",
      "journey-ca-firm.spec.ts",
      "journey-visitor.spec.ts",
    ],
    guideRef: "10, 12, 16; docs/legal/consent-record.md",
    notes:
      "The consent step: terms, privacy notice and profile processing required, reminders and analytics optional, each recorded with the notice version from docs/legal.",
  },
  {
    id: "owner.onboarding.business",
    kind: "page",
    route: "/onboarding/business",
    title: "Add a business",
    section: "owner",
    roles: ONBOARDING_ROLES,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      uses("identity", "GET", "/v1/identity/consents"),
      uses("profile", "POST", "/v1/businesses"),
      uses("profile", "GET", "/v1/ontology"),
    ],
    awaits: [],
    status: "live",
    e2e: [
      "owner-onboarding-business.spec.ts",
      "a11y.spec.ts",
      "journey-owner.spec.ts",
      "journey-ca-firm.spec.ts",
    ],
    guideRef: "2 uc1, F6, 7; ADR-016",
    parent: "owner.onboarding",
    notes:
      "Creates the business from its GSTIN with an Idempotency-Key and shows what the GSTIN lookup returned; asks for the consents first.",
  },
  {
    id: "owner.onboarding.questions",
    kind: "page",
    route: "/onboarding/[businessId]/questions",
    title: "Questions",
    section: "owner",
    roles: ONBOARDING_ROLES,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      uses("profile", "GET", "/v1/businesses/{business_id}/onboarding"),
      uses("profile", "GET", "/v1/businesses/{business_id}"),
      uses("profile", "PATCH", "/v1/businesses/{business_id}"),
      uses("profile", "GET", "/v1/profile/nodes/{node_id}/review-tasks"),
      uses("profile", "GET", "/v1/ontology"),
    ],
    awaits: [],
    status: "live",
    e2e: ["owner-onboarding-questions.spec.ts", "journey-owner.spec.ts"],
    guideRef: "F6; PDF 3.4",
    parent: "owner.onboarding",
    notes:
      "One question at a time from the onboarding checklist, with Not sure and Does not apply, the progress and the review tasks the answers open.",
  },
  {
    id: "owner.onboarding.done",
    kind: "page",
    route: "/onboarding/[businessId]/done",
    title: "Onboarding summary",
    section: "owner",
    roles: ONBOARDING_ROLES,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      uses("profile", "GET", "/v1/businesses/{business_id}"),
      uses("profile", "GET", "/v1/businesses/{business_id}/onboarding"),
      uses("profile", "GET", "/v1/profile/nodes/{node_id}/review-tasks"),
      uses("profile", "GET", "/v1/ontology"),
      BUSINESS_OBLIGATIONS,
    ],
    awaits: [],
    status: "live",
    e2e: [
      "owner-onboarding-questions.spec.ts",
      "journey-owner.spec.ts",
      "product/journey-product.spec.ts",
    ],
    guideRef: "1 metric; F6",
    parent: "owner.onboarding",
    notes:
      "What the profile holds after onboarding: the checklist's counts, the questions left unsure (asked again on request), the open review tasks, and the first obligation as soon as it is worked out (polled, with a timeout).",
  },
  {
    id: "owner.business",
    kind: "page",
    route: "/b/[businessId]",
    title: "Business",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      BUSINESS,
      uses("profile", "GET", "/v1/businesses/{business_id}/onboarding"),
      NODE_REVIEW_TASKS,
    ],
    awaits: [],
    status: "live",
    e2e: ["business-pages.spec.ts", "journey-owner.spec.ts", "journey-ca-firm.spec.ts"],
    guideRef: "2 uc4; ADR-016",
    nav: { group: "business", order: 2 },
    parent: "owner.businesses",
    notes:
      "The business, its registrations, onboarding progress and tiles for the profile pages; its obligations, calendar, changes and Ask are tabs of their own.",
  },
  {
    id: "owner.business.profile",
    kind: "page",
    route: "/b/[businessId]/profile",
    title: "Profile",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      BUSINESS,
      uses("profile", "POST", "/v1/profile/locations"),
      uses("profile", "POST", "/v1/businesses/{business_id}/registrations"),
      uses("identity", "GET", "/v1/identity/consents"),
    ],
    awaits: [],
    status: "live",
    e2e: ["business-pages.spec.ts", "journey-owner.spec.ts"],
    guideRef: "ADR-016",
    nav: { group: "business", order: 3 },
    parent: "owner.business",
    notes:
      "The hierarchy (the entity by its PAN, each registration by its GSTIN), adding a location under a registration, and adding another GSTIN of the business with an Idempotency-Key once the required consents are on file; no route lists a registration's locations yet.",
  },
  {
    id: "owner.business.attributes",
    kind: "page",
    route: "/b/[businessId]/attributes",
    title: "Attributes",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      BUSINESS,
      uses("profile", "PATCH", "/v1/businesses/{business_id}"),
      uses("profile", "GET", "/v1/profile/nodes/{node_id}"),
      uses("profile", "GET", "/v1/ontology"),
    ],
    awaits: [],
    status: "live",
    e2e: ["business-pages.spec.ts", "journey-owner.spec.ts"],
    guideRef: "5 flow 2",
    nav: { group: "business", order: 4 },
    parent: "owner.business",
    notes:
      "A node's own and inherited values for a financial year, what is not answered yet, and changing an answer.",
  },
  {
    id: "owner.business.snapshot",
    kind: "page",
    route: "/b/[businessId]/snapshot",
    title: "Snapshot",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      BUSINESS,
      uses("profile", "GET", "/v1/profile/nodes/{node_id}/snapshot"),
      uses("profile", "GET", "/v1/profile/nodes/{node_id}"),
      uses("profile", "GET", "/v1/ontology"),
    ],
    awaits: [],
    status: "live",
    e2e: ["business-pages.spec.ts", "journey-owner.spec.ts"],
    guideRef: "ADR-016",
    nav: { group: "business", order: 5 },
    parent: "owner.business",
    notes:
      "What the applicability engine evaluates for a node and a financial year, with where each value comes from.",
  },
  {
    id: "owner.business.review-tasks",
    kind: "page",
    route: "/b/[businessId]/review-tasks",
    title: "Review tasks",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [BUSINESS, NODE_REVIEW_TASKS],
    awaits: [unscheduled("profile", "POST", "/v1/profile/review-tasks/{task_id}/resolve")],
    status: "live",
    e2e: ["business-pages.spec.ts", "journey-owner.spec.ts", "journey-ca-firm.spec.ts"],
    guideRef: "8",
    nav: { group: "business", order: 6 },
    parent: "owner.business",
    notes:
      "Lists the tasks the answers opened; resolving one waits for a route nobody has designed.",
  },
  {
    id: "owner.obligations",
    kind: "page",
    route: "/b/[businessId]/obligations",
    title: "Obligations",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [BUSINESS, BUSINESS_OBLIGATIONS],
    awaits: [],
    status: "live",
    e2e: ["owner-obligations.spec.ts", "journey-owner.spec.ts", "product/journey-product.spec.ts"],
    guideRef: "F8",
    nav: { group: "business", order: 9 },
    parent: "owner.business",
  },
  {
    id: "owner.calendar",
    kind: "page",
    route: "/b/[businessId]/calendar",
    title: "Calendar",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [BUSINESS, BUSINESS_OBLIGATIONS],
    awaits: [],
    status: "live",
    e2e: ["owner-obligations.spec.ts", "journey-owner.spec.ts", "product/journey-product.spec.ts"],
    guideRef: "F8",
    nav: { group: "business", order: 10 },
    parent: "owner.business",
  },
  {
    id: "owner.obligation",
    kind: "page",
    route: "/b/[businessId]/obligations/[obligationId]",
    title: "Obligation",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      BUSINESS,
      uses("obligation", "GET", "/v1/obligation/obligations/{obligation_id}"),
      uses("obligation", "POST", "/v1/obligation/obligations/{obligation_id}/status"),
      uses("obligation", "PUT", "/v1/obligation/obligations/{obligation_id}/assignee"),
      uses("obligation", "POST", "/v1/obligation/obligations/{obligation_id}/comments"),
      uses(
        "applicability-engine",
        "GET",
        "/v1/applicability-engine/businesses/{business_id}/decisions",
      ),
      CLAUSE,
      uses("identity", "GET", "/v1/identity/users"),
    ],
    awaits: [],
    status: "live",
    e2e: ["owner-obligations.spec.ts", "product/journey-product.spec.ts"],
    guideRef: "F8, F11, 8, 16",
    parent: "owner.obligations",
  },
  {
    id: "owner.evidence",
    kind: "page",
    route: "/b/[businessId]/obligations/[obligationId]/evidence",
    title: "Evidence",
    section: "owner",
    roles: ["owner", "staff", "compliance_lead"],
    tenantKinds: ["business"],
    uses: [],
    awaits: [
      unscheduled("obligation", "POST", "/v1/obligation/obligations/{obligation_id}/evidence"),
    ],
    status: "planned",
    e2e: [],
    guideRef: "10; G13",
    parent: "owner.obligation",
  },
  {
    id: "owner.changes",
    kind: "page",
    route: "/b/[businessId]/changes",
    title: "Changes",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [BUSINESS, CHANGES, CHANGE_IMPACT, CLAUSE],
    awaits: [],
    status: "live",
    e2e: ["owner-changes.spec.ts", "journey-owner.spec.ts", "product/journey-product.spec.ts"],
    guideRef: "2 uc2, 10",
    nav: { group: "business", order: 7 },
    parent: "owner.business",
  },
  {
    id: "owner.reminders",
    kind: "page",
    route: "/b/[businessId]/reminders",
    title: "Reminders",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [BUSINESS, NOTIFICATIONS],
    awaits: [],
    status: "live",
    e2e: ["owner-reminders.spec.ts"],
    guideRef: "9, F9",
    nav: { group: "business", order: 8 },
    parent: "owner.business",
    notes:
      "The notifications the service recorded for the business, newest first, by delivery state: template, channel, masked address, state, attempts and times. The service keeps no message text.",
  },
  {
    id: "owner.reminder",
    kind: "page",
    route: "/b/[businessId]/reminders/[notificationId]",
    title: "Notification",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [BUSINESS, NOTIFICATION],
    awaits: [],
    status: "live",
    e2e: ["owner-reminders.spec.ts"],
    guideRef: "9, F9",
    parent: "owner.reminders",
    notes:
      "One notification's delivery record: the channel's last error, every time it moved, and the values the message was filled with.",
  },
  {
    id: "owner.report-error",
    kind: "component",
    route: "/b/[businessId]/obligations/[obligationId]",
    title: "Report an error",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [],
    awaits: [
      servicesTrack(
        "WP24",
        "obligation",
        "POST",
        "/v1/obligation/obligations/{obligation_id}/error-reports",
      ),
      servicesTrack("WP24", "obligation", "GET", "/v1/obligation/error-reports"),
    ],
    status: "waiting",
    e2e: [],
    guideRef: "16; G06",
    parent: "owner.obligation",
  },
  {
    id: "owner.ask",
    kind: "page",
    route: "/b/[businessId]/ask",
    title: "Ask",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    flag: "web.qa_enabled",
    uses: [BUSINESS, uses("qa", "POST", "/v1/qa"), RULEBOOK_DOCUMENT],
    awaits: [],
    status: "live",
    e2e: ["owner-ask.spec.ts", "journey-owner.spec.ts", "product/journey-product.spec.ts"],
    guideRef: "2 uc3, F10; ADR-012",
    nav: { group: "business", order: 11 },
    parent: "owner.business",
  },
  {
    id: "owner.answer-feedback",
    kind: "component",
    route: "/b/[businessId]/ask",
    title: "Answer feedback",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [],
    awaits: [
      unscheduled(
        "eval",
        "POST",
        "/v1/eval/triage",
        "an intake route for thumbs-down answers; none is designed",
      ),
    ],
    status: "planned",
    e2e: [],
    guideRef: "8",
  },
  {
    id: "owner.settings",
    kind: "page",
    route: "/settings",
    title: "Settings",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [],
    awaits: [],
    status: "live",
    e2e: [
      "owner-settings.spec.ts",
      "a11y.spec.ts",
      "journey-owner.spec.ts",
      "journey-ca-firm.spec.ts",
    ],
    guideRef: "16",
    nav: { group: "account", order: 2 },
    notes:
      "Every settings and account page the session may open, with its status; the pages still waiting say which route they need.",
  },
  {
    id: "owner.settings.consents",
    kind: "page",
    route: "/settings/consents",
    title: "Consents",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      uses("identity", "GET", "/v1/identity/consents"),
      uses("identity", "POST", "/v1/identity/consents"),
      uses("notification", "PUT", "/v1/notification/preferences/{channel}/{recipient}"),
    ],
    awaits: [],
    status: "live",
    e2e: [
      "owner-settings-consents.spec.ts",
      "a11y.spec.ts",
      "journey-owner.spec.ts",
      "journey-ca-firm.spec.ts",
    ],
    guideRef: "16; docs/legal/consent-record.md",
    nav: { group: "settings", order: 1 },
    parent: "owner.settings",
    notes:
      "The latest record per purpose and every record, oldest first; the optional purposes are given or withdrawn here as new records, and withdrawing WhatsApp reminders also opts the number out.",
  },
  {
    id: "owner.settings.notifications",
    kind: "page",
    route: "/settings/notifications",
    title: "Notifications",
    section: "owner",
    roles: MEMBERS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      uses("notification", "GET", "/v1/notification/preferences/{channel}/{recipient}"),
      uses("notification", "PUT", "/v1/notification/preferences/{channel}/{recipient}"),
      uses("notification", "GET", "/v1/notification/templates"),
      uses("identity", "GET", "/v1/identity/consents"),
    ],
    awaits: [servicesTrack("WP14", "identity", "GET", "/v1/identity/me")],
    status: "live",
    e2e: ["owner-settings-notifications.spec.ts", "a11y.spec.ts", "journey-owner.spec.ts"],
    guideRef: "9, F9; docs/legal/whatsapp-consent.md",
    nav: { group: "settings", order: 2 },
    parent: "owner.settings",
    notes:
      "Per channel, a recipient's preference on the notification service: reminders on or off, the language and the quiet hours; opting in needs the channel's consent. The user's own number and address arrive with the identity route it awaits; until then the page asks and remembers them on the device.",
  },
  {
    id: "owner.settings.billing",
    kind: "page",
    route: "/settings/billing",
    title: "Billing",
    section: "owner",
    roles: TENANT_ADMINS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      uses("identity", "GET", "/v1/identity/billing/plans"),
      uses("identity", "POST", "/v1/identity/billing/subscriptions"),
    ],
    awaits: [servicesTrack("WP25", "identity", "GET", "/v1/identity/entitlements")],
    status: "live",
    e2e: [
      "owner-settings-billing.spec.ts",
      "a11y.spec.ts",
      "journey-owner.spec.ts",
      "journey-ca-firm.spec.ts",
    ],
    guideRef: "6; G32, G33",
    nav: { group: "settings", order: 3 },
    parent: "owner.settings",
    notes:
      "The plans as the identity service states them and starting a subscription with its billing provider; with no provider connected the page says billing is not connected. Plan usage and entitlement limits arrive with the route it awaits.",
  },
  {
    id: "owner.settings.notification-recipients",
    kind: "page",
    route: "/settings/notifications/recipients",
    title: "Notification recipients",
    section: "owner",
    roles: TENANT_ADMINS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [
      uses("profile", "GET", "/v1/businesses"),
      uses("notification", "GET", "/v1/notification/recipients"),
      uses("notification", "PUT", "/v1/notification/recipients/{recipient_id}"),
      uses("notification", "GET", "/v1/notification/recipients/{recipient_id}"),
      uses("notification", "DELETE", "/v1/notification/recipients/{recipient_id}"),
      uses("notification", "GET", "/v1/notification/templates"),
    ],
    awaits: [],
    status: "live",
    e2e: ["owner-settings-recipients.spec.ts", "a11y.spec.ts"],
    guideRef: "9, F9",
    nav: { group: "settings", order: 4 },
    parent: "owner.settings.notifications",
    notes:
      "Who hears about each business: a business's recipients with their addresses in the order tried, language, delivery and businesses; adding, changing and removing one. An address still needs its opt-in.",
  },
  {
    id: "owner.settings.data-rights",
    kind: "page",
    route: "/settings/data-rights",
    title: "Data rights",
    section: "owner",
    roles: TENANT_ADMINS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [],
    awaits: [
      servicesTrack("WP24", "identity", "POST", "/v1/identity/data-requests"),
      servicesTrack("WP24", "identity", "GET", "/v1/identity/data-requests"),
      servicesTrack("WP24", "identity", "GET", "/v1/identity/data-requests/{request_id}"),
      DATA_EXPORT,
    ],
    status: "waiting",
    preview: "PrivacyRightsSection",
    e2e: [],
    guideRef: "16 DPDP; G37",
    nav: { group: "settings", order: 5 },
    parent: "owner.settings",
  },
  {
    id: "owner.settings.team",
    kind: "page",
    route: "/settings/team",
    title: "Team",
    section: "owner",
    roles: TENANT_ADMINS,
    tenantKinds: BUSINESS_TENANTS,
    uses: IDENTITY_USER_ROUTES,
    awaits: IDENTITY_USERS,
    status: "ready",
    e2e: [],
    guideRef: "5, 6, 16",
    nav: { group: "settings", order: 6 },
    parent: "owner.settings",
  },
  {
    id: "owner.settings.activity",
    kind: "page",
    route: "/settings/activity",
    title: "Activity",
    section: "owner",
    roles: ["owner", "ca_admin", "compliance_lead"],
    tenantKinds: BUSINESS_TENANTS,
    uses: [],
    awaits: [servicesTrack("WP17", "identity", "GET", "/v1/identity/audit")],
    status: "waiting",
    e2e: [],
    guideRef: "10 GET /v1/audit; F11",
    nav: { group: "settings", order: 7 },
    parent: "owner.settings",
  },
  // ---- ca ---------------------------------------------------------------------------------
  {
    id: "ca.change-impact",
    kind: "page",
    route: "/changes/[ruleVersionId]/impact",
    title: "Affected clients",
    section: "ca",
    roles: CA,
    tenantKinds: ["ca_firm"],
    uses: [
      CHANGE_IMPACT,
      RULE_VERSION,
      BUSINESS,
      uses("notification", "POST", "/v1/notification/bulk"),
    ],
    awaits: [],
    status: "live",
    e2e: ["ca-change-impact.spec.ts", "product/journey-oversight.spec.ts"],
    guideRef: "2 uc5, 10, 15; G75",
    parent: "owner.businesses",
  },
  {
    id: "ca.clients",
    kind: "page",
    route: "/clients",
    title: "Clients",
    section: "ca",
    roles: CA,
    tenantKinds: ["ca_firm"],
    uses: [],
    awaits: [
      unscheduled("profile", "GET", "/v1/businesses/summary"),
      unscheduled("obligation", "POST", "/v1/obligation/obligations/bulk-status"),
    ],
    status: "planned",
    e2e: [],
    guideRef: "F12",
    nav: { group: "clients", order: 1 },
  },
  {
    id: "ca.settings.webhooks",
    kind: "page",
    route: "/settings/webhooks",
    title: "Webhooks",
    section: "ca",
    roles: ["ca_admin"],
    tenantKinds: ["ca_firm"],
    uses: [],
    awaits: [
      unscheduled("notification", "POST", "/v1/webhooks"),
      unscheduled("notification", "GET", "/v1/webhooks/{webhook_id}/deliveries"),
    ],
    status: "planned",
    e2e: [],
    guideRef: "10; F13; G35",
    nav: { group: "settings", order: 8 },
    parent: "owner.settings",
  },
  {
    id: "ca.settings.api-keys",
    kind: "page",
    route: "/settings/api-keys",
    title: "API keys",
    section: "ca",
    roles: TENANT_ADMINS,
    tenantKinds: BUSINESS_TENANTS,
    uses: [],
    awaits: [
      unscheduled("identity", "POST", "/v1/identity/api-keys"),
      unscheduled("identity", "GET", "/v1/identity/api-keys"),
      unscheduled("identity", "DELETE", "/v1/identity/api-keys/{key_id}"),
    ],
    status: "planned",
    e2e: [],
    guideRef: "10, 15; G32, G35",
    nav: { group: "settings", order: 9 },
    parent: "owner.settings",
  },
  {
    id: "ca.settings.digests",
    kind: "page",
    route: "/settings/digests",
    title: "Digests",
    section: "ca",
    roles: ["ca_admin"],
    tenantKinds: ["ca_firm"],
    uses: [],
    awaits: [
      unscheduled("notification", "PUT", "/v1/notification/recipients/{recipient_id}/digest"),
    ],
    status: "planned",
    e2e: [],
    guideRef: "F12",
    nav: { group: "settings", order: 10 },
    parent: "owner.settings",
  },
  // ---- admin ------------------------------------------------------------------------------
  {
    id: "admin.home",
    kind: "page",
    route: "/admin",
    title: "Internal tools",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      uses("rulebook", "GET", "/v1/rulebook/review/entities"),
      uses("rulebook", "GET", "/v1/rulebook/review/relations"),
      uses("rulebook", "GET", "/v1/rulebook/rules"),
      uses("llm-gateway", "GET", "/v1/llm-gateway/prompts"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-home.spec.ts", "admin-gate.spec.ts", "a11y.spec.ts"],
    guideRef: "14, 15, 17",
    notes:
      "Also probes GET /health on every service, the py-common liveness route each spec lists.",
  },
  {
    id: "admin.not-available",
    kind: "page",
    route: "/admin/[...slug]",
    title: "Not available yet",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["not-available.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    parent: "admin.home",
    notes: "Catch-all serving every admin tool that is not built, from its registry entry.",
  },
  {
    id: "admin.team",
    kind: "page",
    route: "/admin/team",
    title: "Internal users",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: IDENTITY_USER_ROUTES,
    awaits: IDENTITY_USERS,
    status: "ready",
    e2e: [],
    guideRef: "15, 17",
    nav: { group: "identity", order: 3 },
    parent: "admin.home",
  },
  {
    id: "admin.rulebook.documents",
    kind: "page",
    route: "/admin/rulebook/documents",
    title: "Documents",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("rulebook", "GET", "/v1/rulebook/documents/{document_id}")],
    awaits: [servicesTrack("WP18", "pipeline", "GET", "/v1/pipeline/sources/{key}/documents")],
    status: "live",
    e2e: ["admin-rulebook-documents.spec.ts", "a11y.spec.ts"],
    guideRef: "15; ADR-018",
    nav: { group: "rulebook", order: 1 },
    parent: "admin.home",
    notes:
      "Opens one document by its id or its sha256; a list of documents arrives with the source manager's document route.",
  },
  {
    id: "admin.rulebook.document",
    kind: "page",
    route: "/admin/rulebook/documents/[documentId]",
    title: "Document",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("rulebook", "GET", "/v1/rulebook/documents/{document_id}")],
    awaits: [],
    status: "live",
    e2e: ["admin-rulebook-documents.spec.ts"],
    guideRef: "15",
    parent: "admin.rulebook.documents",
  },
  {
    id: "admin.rulebook.entities",
    kind: "page",
    route: "/admin/rulebook/entities",
    title: "Entity review",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("rulebook", "GET", "/v1/rulebook/review/entities")],
    awaits: [],
    status: "live",
    e2e: ["admin-entity-review.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "rulebook", order: 2 },
    parent: "admin.home",
  },
  {
    id: "admin.rulebook.entities.group",
    kind: "page",
    route: "/admin/rulebook/entities/group",
    title: "Entity group",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      uses("rulebook", "GET", "/v1/rulebook/review/entities/items"),
      uses("rulebook", "POST", "/v1/rulebook/review/entities/decisions"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-entity-review.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    parent: "admin.rulebook.entities",
  },
  {
    id: "admin.rulebook.relations",
    kind: "page",
    route: "/admin/rulebook/relations",
    title: "Relation candidates",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [REVIEW_RELATIONS],
    awaits: [],
    status: "live",
    e2e: ["admin-relation-review.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "rulebook", order: 3 },
    parent: "admin.home",
  },
  {
    id: "admin.rulebook.relation",
    kind: "page",
    route: "/admin/rulebook/relations/[candidateId]",
    title: "Relation candidate",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      REVIEW_RELATIONS,
      CLAUSE,
      uses("rulebook", "GET", "/v1/rulebook/rules"),
      uses("rulebook", "GET", "/v1/rulebook/rules/{rule_key}/versions"),
      uses("rulebook", "POST", "/v1/rulebook/review/relations/{candidate_id}/approve"),
      uses("rulebook", "POST", "/v1/rulebook/review/relations/{candidate_id}/reject"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-relation-review.spec.ts"],
    guideRef: "15; ADR-018",
    parent: "admin.rulebook.relations",
  },
  {
    id: "admin.rulebook.relations.graph",
    kind: "page",
    route: "/admin/rulebook/relations/graph",
    title: "Relations graph",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [RELATIONS, RULE_VERSION],
    awaits: [],
    status: "live",
    e2e: ["admin-rulebook-graph.spec.ts", "a11y.spec.ts"],
    guideRef: "15; ADR-017",
    parent: "admin.rulebook.relations",
  },
  {
    id: "admin.rulebook.rules",
    kind: "page",
    route: "/admin/rulebook/rules",
    title: "Rules",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("rulebook", "GET", "/v1/rulebook/rules")],
    awaits: [],
    status: "live",
    e2e: ["admin-rulebook-rules.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "rulebook", order: 4 },
    parent: "admin.home",
  },
  {
    id: "admin.rulebook.versions",
    kind: "page",
    route: "/admin/rulebook/versions",
    title: "Rule versions",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      RULE_VERSIONS,
      uses("rulebook", "GET", "/v1/rulebook/rules"),
      uses("rulebook", "GET", "/v1/rulebook/rules/{rule_key}/versions"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-rulebook-versions.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "rulebook", order: 5 },
    parent: "admin.home",
  },
  {
    id: "admin.rulebook.version",
    kind: "page",
    route: "/admin/rulebook/versions/[ruleVersionId]",
    title: "Rule version",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      RULE_VERSION,
      uses("rulebook", "GET", "/v1/rulebook/rule-versions/{rule_version_id}/citations"),
      uses("rulebook", "PUT", "/v1/rulebook/rule-versions/{rule_version_id}/citations"),
      uses("rulebook", "POST", "/v1/rulebook/rule-versions/{rule_version_id}/submit"),
      uses("rulebook", "POST", "/v1/rulebook/rule-versions/{rule_version_id}/return"),
      uses("rulebook", "POST", "/v1/rulebook/rule-versions/{rule_version_id}/approve"),
      uses("rulebook", "POST", "/v1/rulebook/rule-versions/{rule_version_id}/publish"),
      uses("rulebook", "POST", "/v1/rulebook/rule-versions/{rule_version_id}/withdraw"),
      CLAUSE,
      RELATIONS,
      uses("profile", "GET", "/v1/ontology"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-rulebook-versions.spec.ts", "admin-rulebook-publish.spec.ts"],
    guideRef: "ADR-006; F4, 6",
    parent: "admin.rulebook.versions",
  },
  {
    id: "admin.rulebook.canonical",
    kind: "page",
    route: "/admin/rulebook/entities/canonical",
    title: "Canonical entities",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("rulebook", "GET", "/v1/rulebook/entities/resolve")],
    awaits: [],
    status: "live",
    e2e: ["admin-rulebook-entities.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "rulebook", order: 6 },
    parent: "admin.home",
  },
  {
    id: "admin.rulebook.canonical.entity",
    kind: "page",
    route: "/admin/rulebook/entities/canonical/[entityId]",
    title: "Canonical entity",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      ENTITY,
      uses("rulebook", "GET", "/v1/rulebook/entities/{entity_id}/clauses"),
      RELATIONS,
      RULE_VERSION,
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-rulebook-entities.spec.ts"],
    guideRef: "15",
    parent: "admin.rulebook.canonical",
  },
  {
    id: "admin.rulebook.search",
    kind: "page",
    route: "/admin/rulebook/search",
    title: "Clause search",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("rulebook", "POST", "/v1/rulebook/search")],
    awaits: [],
    status: "live",
    e2e: ["admin-rulebook-search.spec.ts", "a11y.spec.ts"],
    guideRef: "15; ADR-012",
    nav: { group: "rulebook", order: 7 },
    parent: "admin.home",
  },
  {
    id: "admin.review",
    kind: "page",
    route: "/admin/review",
    title: "Review queue",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [REVIEW_TASKS, REVIEW_CLAIM, REVIEW_SEED, REVIEW_STATS_READ],
    awaits: [
      servicesTrack("WP21", "rulebook", "GET", "/v1/rulebook/review/tasks"),
      servicesTrack("WP21", "rulebook", "POST", "/v1/rulebook/review/tasks/{task_id}/claim"),
      servicesTrack("WP21", "rulebook", "POST", "/v1/rulebook/review/tasks/seed"),
      REVIEW_STATS,
    ],
    status: "ready",
    e2e: [],
    guideRef: "15; F4; ADR-006",
    nav: { group: "review", order: 1 },
    parent: "admin.home",
  },
  {
    id: "admin.review.task",
    kind: "page",
    route: "/admin/review/[taskId]",
    title: "Review workbench",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      uses("rulebook", "GET", "/v1/rulebook/documents/{document_id}"),
      RULE_VERSION,
      uses("profile", "GET", "/v1/ontology"),
      STORED_BYTES,
      REVIEW_TASK,
      REVIEW_CLAIM,
      REVIEW_DRAFT,
      REVIEW_EDIT,
      REVIEW_DECIDE,
    ],
    awaits: [
      servicesTrack("WP21", "rulebook", "GET", "/v1/rulebook/review/tasks/{task_id}"),
      servicesTrack("WP21", "rulebook", "POST", "/v1/rulebook/review/tasks/{task_id}/draft"),
      servicesTrack("WP21", "rulebook", "PATCH", "/v1/rulebook/review/tasks/{task_id}/draft"),
      servicesTrack("WP21", "rulebook", "POST", "/v1/rulebook/review/tasks/{task_id}/decide"),
      ONTOLOGY,
      RAW_DOCUMENT,
    ],
    status: "ready",
    e2e: [],
    guideRef: "15; ADR-006; F4",
    parent: "admin.review",
  },
  {
    id: "admin.review.stats",
    kind: "page",
    route: "/admin/review/stats",
    title: "Review stats",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [REVIEW_STATS_READ],
    awaits: [REVIEW_STATS],
    status: "ready",
    e2e: [],
    guideRef: "15",
    nav: { group: "review", order: 2 },
    parent: "admin.review",
  },
  {
    id: "admin.review-sampling",
    kind: "component",
    route: "/admin/review",
    title: "Review sampling",
    section: "admin",
    roles: ["reviewer", "admin"],
    tenantKinds: ["internal"],
    uses: [],
    awaits: [unscheduled("rulebook", "POST", "/v1/rulebook/review/samples")],
    status: "planned",
    e2e: [],
    guideRef: "19; G77",
    parent: "admin.review",
  },
  {
    id: "admin.error-reports",
    kind: "page",
    route: "/admin/error-reports",
    title: "Error reports",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [RELATIONS],
    awaits: [
      servicesTrack("WP24", "rulebook", "GET", "/v1/rulebook/error-reports"),
      servicesTrack("WP24", "rulebook", "POST", "/v1/rulebook/error-reports/{report_id}/decision"),
    ],
    status: "waiting",
    e2e: [],
    guideRef: "16; G06",
    nav: { group: "review", order: 3 },
    parent: "admin.home",
  },
  {
    id: "admin.decisions",
    kind: "page",
    route: "/admin/decisions",
    title: "Decision review",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      uses("applicability-engine", "GET", "/v1/applicability-engine/review-items"),
      uses(
        "applicability-engine",
        "POST",
        "/v1/applicability-engine/review-items/{item_id}/resolve",
      ),
      RULE_VERSION,
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-decisions.spec.ts", "a11y.spec.ts"],
    guideRef: "8; F7; ADR-007",
    nav: { group: "review", order: 4 },
    parent: "admin.home",
  },
  {
    id: "admin.qa-triage",
    kind: "page",
    route: "/admin/qa-triage",
    title: "Q&A triage",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [],
    awaits: [
      servicesTrack("WP28", "eval", "GET", "/v1/eval/triage"),
      servicesTrack("WP28", "eval", "POST", "/v1/eval/triage/{item_id}/decision"),
      QA_COVERAGE,
    ],
    status: "waiting",
    e2e: [],
    guideRef: "8; G126",
    nav: { group: "review", order: 5 },
    parent: "admin.home",
  },
  {
    id: "admin.sources",
    kind: "page",
    route: "/admin/sources",
    title: "Sources",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [SOURCE_LIST, SOURCE_ADD, SOURCE_EDIT, SOURCE_FETCH, SOURCE_DOCUMENTS],
    awaits: [
      servicesTrack("WP18", "pipeline", "GET", "/v1/pipeline/sources"),
      servicesTrack("WP18", "pipeline", "POST", "/v1/pipeline/sources"),
      servicesTrack("WP18", "pipeline", "PATCH", "/v1/pipeline/sources/{key}"),
      servicesTrack("WP18", "pipeline", "POST", "/v1/pipeline/sources/{key}/fetch"),
      servicesTrack("WP18", "pipeline", "GET", "/v1/pipeline/sources/{key}/documents"),
    ],
    status: "ready",
    e2e: [],
    guideRef: "15; 7",
    nav: { group: "operations", order: 1 },
    parent: "admin.home",
  },
  {
    id: "admin.source",
    kind: "page",
    route: "/admin/sources/[key]",
    title: "Source history",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [SOURCE_DOCUMENTS, STORED_DOCUMENT, STORED_BYTES],
    awaits: [
      servicesTrack("WP18", "pipeline", "GET", "/v1/pipeline/sources/{key}/documents"),
      servicesTrack("WP18", "pipeline", "GET", "/v1/pipeline/documents/{document_id}"),
      RAW_DOCUMENT,
    ],
    status: "ready",
    e2e: [],
    guideRef: "15",
    parent: "admin.sources",
  },
  {
    id: "admin.pipeline",
    kind: "page",
    route: "/admin/pipeline",
    title: "Pipeline",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [RUNS, EVERY_DOCUMENT, DOCUMENT_RETRY, DEAD_OUTBOX, OUTBOX_REQUEUE],
    awaits: [
      servicesTrack("WP19", "pipeline", "GET", "/v1/pipeline/runs"),
      servicesTrack("WP19", "pipeline", "GET", "/v1/pipeline/documents"),
      servicesTrack("WP19", "pipeline", "POST", "/v1/pipeline/documents/{document_id}/retry"),
      servicesTrack("WP19", "pipeline", "GET", "/v1/pipeline/outbox/dead"),
      servicesTrack("WP19", "pipeline", "POST", "/v1/pipeline/outbox/{event_id}/requeue"),
    ],
    status: "ready",
    e2e: [],
    guideRef: "15; 5",
    nav: { group: "operations", order: 2 },
    parent: "admin.home",
  },
  {
    id: "admin.pipeline.tasks",
    kind: "page",
    route: "/admin/pipeline/tasks",
    title: "Pipeline tasks",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [TASKS, TASK_RESOLVE, TASK_DISMISS, UPLOAD],
    awaits: [
      servicesTrack("WP19", "pipeline", "GET", "/v1/pipeline/tasks"),
      servicesTrack("WP19", "pipeline", "POST", "/v1/pipeline/tasks/{task_id}/resolve"),
      servicesTrack("WP19", "pipeline", "POST", "/v1/pipeline/tasks/{task_id}/dismiss"),
      UPLOADS,
    ],
    status: "ready",
    e2e: [],
    guideRef: "7, 15; G47, G48",
    nav: { group: "operations", order: 3 },
    parent: "admin.pipeline",
  },
  {
    id: "admin.llm.edit-controls",
    kind: "component",
    route: "/admin/llm/prompts",
    title: "Prompt and model edits",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: [
      uses("llm-gateway", "GET", "/v1/llm-gateway/prompts"),
      uses("llm-gateway", "GET", "/v1/llm-gateway/models"),
    ],
    awaits: [
      unscheduled(
        "llm-gateway",
        "PUT",
        "/v1/llm-gateway/prompts/{name}",
        "write route not yet committed; WP27 tags it admin when it is",
      ),
      unscheduled(
        "llm-gateway",
        "PUT",
        "/v1/llm-gateway/models/{feature}",
        "write route not yet committed; WP27 tags it admin when it is",
      ),
    ],
    status: "planned",
    e2e: [],
    guideRef: "15; G79",
    parent: "admin.home",
  },
  {
    id: "admin.notifications",
    kind: "page",
    route: "/admin/notifications",
    title: "Notifications",
    section: "admin",
    roles: ["analyst", "admin"],
    tenantKinds: ["internal"],
    uses: [NOTIFICATIONS],
    awaits: [],
    status: "live",
    e2e: ["admin-notifications.spec.ts", "a11y.spec.ts"],
    guideRef: "15; 9",
    nav: { group: "operations", order: 4 },
    parent: "admin.home",
    notes:
      "Read-only: a business's notifications looked up by tenant id and business id (the routes are tenant-scoped), by delivery state, addresses masked. Resend is its own entry, admin.notification.resend.",
  },
  {
    id: "admin.notification",
    kind: "page",
    route: "/admin/notifications/[notificationId]",
    title: "Notification",
    section: "admin",
    roles: ["analyst", "admin"],
    tenantKinds: ["internal"],
    uses: [NOTIFICATION],
    awaits: [],
    status: "live",
    e2e: ["admin-notifications.spec.ts"],
    guideRef: "15",
    parent: "admin.notifications",
    notes:
      "One notification of the tenant named in ?tenant=, with the ids an operator traces a delivery by.",
  },
  {
    id: "admin.notification.resend",
    kind: "capability",
    route: "/admin/notifications/[notificationId]",
    title: "Resend a notification",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: [],
    awaits: [
      {
        ...servicesTrack(
          "WP30",
          "notification",
          "POST",
          "/v1/notification/notifications/{notification_id}/resend",
        ),
        header: "Idempotency-Key",
      },
    ],
    status: "waiting",
    e2e: [],
    guideRef: "15; 9",
    parent: "admin.notification",
    notes:
      "Queue a notification that failed for good again, with a reason, by an admin; it waits for the hardened route (reason, admin role, Idempotency-Key, audit). The route on main takes none of them, so the console does not offer it.",
  },
  {
    id: "admin.notifications.templates",
    kind: "page",
    route: "/admin/notifications/templates",
    title: "Message templates",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("notification", "GET", "/v1/notification/templates")],
    awaits: [],
    status: "live",
    e2e: ["admin-notifications.spec.ts", "a11y.spec.ts"],
    guideRef: "15; 9",
    nav: { group: "operations", order: 5 },
    parent: "admin.notifications",
    notes:
      "Every message template with its channel, language, Meta name, approval status, placeholders and text, as the notification service holds them.",
  },
  {
    id: "admin.ontology",
    kind: "page",
    route: "/admin/ontology",
    title: "Ontology",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("profile", "GET", "/v1/ontology")],
    awaits: [],
    status: "live",
    e2e: ["admin-ontology.spec.ts", "a11y.spec.ts"],
    guideRef: "15; G25",
    nav: { group: "operations", order: 6 },
    parent: "admin.home",
    notes:
      "The attributes by level with their questions, help, meanings, allowed values, examples and rule operators; read-only. The usage per attribute is its own entry, admin.ontology.usage.",
  },
  {
    id: "admin.ontology.usage",
    kind: "component",
    route: "/admin/ontology",
    title: "Attribute usage",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [RULE_VERSIONS],
    awaits: [servicesTrack("WP30", "profile", "GET", "/v1/profile/admin/attribute-usage")],
    status: "waiting",
    e2e: [],
    guideRef: "15; G25",
    parent: "admin.ontology",
    notes:
      "How many profiles hold each attribute and in which state, and the rules in force that read it, on the ontology browser; the counts wait for the profile admin route.",
  },
  {
    id: "admin.flags",
    kind: "page",
    route: "/admin/flags",
    title: "Feature flags",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [],
    awaits: [],
    status: "live",
    e2e: ["admin-flags.spec.ts", "a11y.spec.ts"],
    guideRef: "15; G90",
    nav: { group: "operations", order: 7 },
    parent: "admin.home",
    notes:
      "Every flag in packages/flags/registry.json with its owner, default and expiry; the value the web server's reader answers for the flags the web app reads. No flag is changed here.",
  },
  {
    id: "admin.audit",
    kind: "page",
    route: "/admin/audit",
    title: "Audit trail",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [],
    awaits: [servicesTrack("WP17", "identity", "GET", "/v1/identity/audit")],
    status: "waiting",
    e2e: [],
    guideRef: "15, 16; G36",
    nav: { group: "operations", order: 8 },
    parent: "admin.home",
  },
  {
    id: "admin.tenants",
    kind: "page",
    route: "/admin/tenants",
    title: "Tenants",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: [],
    awaits: [servicesTrack("WP30", "identity", "GET", "/v1/identity/admin/tenants")],
    status: "waiting",
    e2e: [],
    guideRef: "15; G80",
    nav: { group: "identity", order: 1 },
    parent: "admin.home",
  },
  {
    id: "admin.tenant",
    kind: "page",
    route: "/admin/tenants/[tenantId]",
    title: "Tenant",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: [],
    awaits: [
      servicesTrack("WP30", "identity", "GET", "/v1/identity/admin/tenants/{tenant_id}"),
      servicesTrack("WP30", "identity", "GET", "/v1/identity/admin/tenants/{tenant_id}/users"),
    ],
    status: "waiting",
    e2e: [],
    guideRef: "15; G80",
    parent: "admin.tenants",
  },
  {
    id: "admin.tenant.impersonate",
    kind: "page",
    route: "/admin/tenants/[tenantId]/impersonate",
    title: "Impersonate",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: [],
    awaits: [unscheduled("identity", "POST", "/v1/identity/admin/impersonations")],
    status: "planned",
    e2e: [],
    guideRef: "15; G80",
    parent: "admin.tenant",
  },
  {
    id: "admin.impact",
    kind: "page",
    route: "/admin/impact",
    title: "Impact explorer",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: [
      uses("profile", "GET", "/v1/ontology"),
      uses("applicability-engine", "POST", "/v1/applicability-engine/dry-runs"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-impact.spec.ts", "a11y.spec.ts", "product/journey-oversight.spec.ts"],
    guideRef: "15; G04",
    nav: { group: "engine", order: 1 },
    parent: "admin.home",
  },
  {
    id: "admin.fan-outs",
    kind: "page",
    route: "/admin/fan-outs",
    title: "Fan-outs",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      RULE_VERSION,
      uses("applicability-engine", "GET", "/v1/applicability-engine/fan-outs"),
      uses("applicability-engine", "GET", "/v1/applicability-engine/fan-out-hold"),
      uses("applicability-engine", "PUT", "/v1/applicability-engine/fan-out-hold"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-fan-outs.spec.ts", "a11y.spec.ts", "product/journey-oversight.spec.ts"],
    guideRef: "16, 18; G03, G05",
    nav: { group: "engine", order: 2 },
    parent: "admin.home",
  },
  {
    id: "admin.fan-out",
    kind: "page",
    route: "/admin/fan-outs/[ruleVersionId]",
    title: "Fan-out control",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      RULE_VERSION,
      uses("applicability-engine", "GET", "/v1/applicability-engine/fan-outs/{rule_version_id}"),
      uses("applicability-engine", "GET", "/v1/applicability-engine/fan-out-hold"),
      uses("applicability-engine", "PUT", "/v1/applicability-engine/fan-out-hold"),
      uses(
        "applicability-engine",
        "POST",
        "/v1/applicability-engine/fan-outs/{rule_version_id}/pause",
      ),
      uses(
        "applicability-engine",
        "POST",
        "/v1/applicability-engine/fan-outs/{rule_version_id}/resume",
      ),
      uses(
        "applicability-engine",
        "POST",
        "/v1/applicability-engine/fan-outs/{rule_version_id}/cancel",
      ),
      uses("rulebook", "POST", "/v1/rulebook/rule-versions/{rule_version_id}/withdraw"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-fan-outs.spec.ts", "product/journey-oversight.spec.ts"],
    guideRef: "16; PDF 8.1; G05",
    parent: "admin.fan-outs",
  },
  {
    id: "admin.evals",
    kind: "page",
    route: "/admin/evals",
    title: "Evals",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("eval", "GET", "/v1/eval/runs")],
    awaits: [
      servicesTrack("WP27", "eval", "GET", "/v1/eval/deliveries"),
      BUDGET_ALARMS,
      QA_COVERAGE,
    ],
    status: "waiting",
    e2e: [],
    guideRef: "8, 15; G67",
    nav: { group: "evals", order: 1 },
    parent: "admin.home",
  },
  {
    id: "admin.evals.run",
    kind: "page",
    route: "/admin/evals/runs/[runId]",
    title: "Eval run",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("eval", "GET", "/v1/eval/runs/{run_id}")],
    awaits: [],
    status: "ready",
    e2e: [],
    guideRef: "8, 15",
    parent: "admin.evals",
  },
  {
    id: "admin.evals.compare",
    kind: "page",
    route: "/admin/evals/compare",
    title: "Compare prompt versions",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [],
    awaits: [
      unscheduled("eval", "POST", "/v1/eval/comparisons"),
      unscheduled("eval", "POST", "/v1/eval/golden-sets/{set_id}/approve"),
    ],
    status: "planned",
    e2e: [],
    guideRef: "15; G118",
    parent: "admin.evals",
  },
  {
    id: "admin.costs",
    kind: "page",
    route: "/admin/costs",
    title: "Costs",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: [],
    awaits: [servicesTrack("WP27", "eval", "GET", "/v1/eval/costs"), BUDGET_ALARMS],
    status: "waiting",
    e2e: [],
    guideRef: "15; G118",
    nav: { group: "evals", order: 2 },
    parent: "admin.home",
  },
  {
    id: "admin.llm.prompts",
    kind: "page",
    route: "/admin/llm/prompts",
    title: "Prompts",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("llm-gateway", "GET", "/v1/llm-gateway/prompts")],
    awaits: [],
    status: "live",
    e2e: ["admin-llm.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "evals", order: 3 },
    parent: "admin.home",
  },
  {
    id: "admin.llm.models",
    kind: "page",
    route: "/admin/llm/models",
    title: "Model routes",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("llm-gateway", "GET", "/v1/llm-gateway/models")],
    awaits: [],
    status: "live",
    e2e: ["admin-llm.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "evals", order: 4 },
    parent: "admin.home",
  },
  {
    id: "admin.llm.usage",
    kind: "page",
    route: "/admin/llm/usage",
    title: "Usage and budgets",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [uses("llm-gateway", "GET", "/v1/llm-gateway/usage")],
    awaits: [],
    status: "live",
    e2e: ["admin-llm.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "evals", order: 5 },
    parent: "admin.home",
  },
  {
    id: "admin.profiles.review-tasks",
    kind: "page",
    route: "/admin/profiles/review-tasks",
    title: "Profile review tasks",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: [
      uses("profile", "GET", "/v1/profile/nodes/{node_id}"),
      NODE_REVIEW_TASKS,
      uses("profile", "GET", "/v1/profile/nodes/{node_id}/snapshot"),
      uses("profile", "GET", "/v1/ontology"),
    ],
    awaits: [],
    status: "live",
    e2e: ["admin-profile-review-tasks.spec.ts", "a11y.spec.ts"],
    guideRef: "15",
    nav: { group: "identity", order: 2 },
    parent: "admin.home",
  },
  {
    id: "admin.system",
    kind: "page",
    route: "/admin/system",
    title: "System",
    section: "admin",
    roles: REGULATORY,
    tenantKinds: ["internal"],
    uses: PROBES,
    awaits: [],
    status: "ready",
    e2e: [],
    guideRef: "14, 18",
    nav: { group: "operations", order: 9 },
    parent: "admin.home",
    notes:
      "Every service's health and readiness with its version and latency, the ports and the web app's facts; the pipeline's probes are the same py-common routes outside a committed spec.",
  },
  {
    id: "admin.backfill",
    kind: "page",
    route: "/admin/backfill",
    title: "Backfill and replay",
    section: "admin",
    roles: ["admin"],
    tenantKinds: ["internal"],
    uses: [],
    awaits: [unscheduled("pipeline", "POST", "/v1/pipeline/backfills")],
    status: "planned",
    e2e: [],
    guideRef: "15; G53",
    nav: { group: "operations", order: 10 },
    parent: "admin.home",
    notes:
      'The command line is the current path: make backfill ARGS="--plan services/pipeline/backfill-plan.yaml --dry-run | --workflow | --report" runs the crawl workflow per plan row, make replay lists and replays dead letters, and the pipeline screen requeues dead outbox rows.',
  },
] as const satisfies readonly Screen[];

export type ScreenId = (typeof SCREEN_LIST)[number]["id"];

export const SCREENS: readonly Screen[] = SCREEN_LIST;

export function isScreenId(value: string): value is ScreenId {
  return SCREEN_LIST.some((screen) => screen.id === value);
}

export function screenById(id: ScreenId): Screen {
  const screen = SCREENS.find((entry) => entry.id === id);
  if (screen === undefined) throw new Error(`unknown screen: ${id}`);
  return screen;
}

export function isCatchAll(route: string): boolean {
  return route.includes("[...");
}

/** The parameter names in a route: /b/[businessId]/obligations/[obligationId] -> businessId, obligationId. */
export function routeParams(route: string): string[] {
  return [...route.matchAll(/\[(?:\.\.\.)?([^\]]+)\]/g)].map((match) => match[1] as string);
}

/** A regular expression matching a concrete pathname against a route with dynamic segments. */
export function toRoutePattern(route: string): RegExp {
  const source = route
    .split("/")
    .map((segment) => {
      if (/^\[\.\.\..+\]$/.test(segment)) return "(.+)";
      if (/^\[.+\]$/.test(segment)) return "([^/]+)";
      return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  return new RegExp(`^${source}/?$`);
}

export interface ScreenMatch {
  screen: Screen;
  params: Record<string, string>;
}

function staticSegments(route: string): number {
  return route.split("/").filter((segment) => segment !== "" && !segment.startsWith("[")).length;
}

/** Pages ordered so that /settings/team wins over /b/[businessId] and static routes over dynamic ones. */
const PAGES_BY_SPECIFICITY: readonly Screen[] = SCREENS.filter(
  (screen) => screen.kind === "page" && !isCatchAll(screen.route),
).sort(
  (a, b) =>
    staticSegments(b.route) - staticSegments(a.route) ||
    routeParams(a.route).length - routeParams(b.route).length,
);

/** The page entry a pathname belongs to, with its parameters decoded; null for unknown paths. */
export function matchScreen(pathname: string): ScreenMatch | null {
  for (const screen of PAGES_BY_SPECIFICITY) {
    const match = toRoutePattern(screen.route).exec(pathname);
    if (match === null) continue;
    const params: Record<string, string> = {};
    routeParams(screen.route).forEach((name, index) => {
      params[name] = decodeURIComponent(match[index + 1] as string);
    });
    return { screen, params };
  }
  return null;
}

/** The concrete href for a screen; typed routes accept it, and a missing parameter throws. */
export function hrefFor(screen: Screen, params: Readonly<Record<string, string>> = {}): Route {
  const href = screen.route.replace(/\[(?:\.\.\.)?([^\]]+)\]/g, (_, name: string) => {
    const value = params[name];
    if (value === undefined) throw new Error(`${screen.id}: missing route parameter "${name}"`);
    return encodeURIComponent(value);
  });
  return href as Route;
}

/**
 * The href of the live page registered at a static route, or null while that page is not built:
 * a link to a tool from elsewhere (a count tile, a "show all" link) appears once the tool does.
 */
export function livePageHref(route: string): Route | null {
  const screen = SCREENS.find(
    (entry) => entry.kind === "page" && entry.route === route && entry.status === "live",
  );
  if (screen === undefined || routeParams(screen.route).length > 0) return null;
  return hrefFor(screen);
}

/** The screens a principal may open: public ones, or those sharing a role with it. */
export function screensFor(
  roles: readonly Role[] | null,
  tenantKind?: TenantKind,
): readonly Screen[] {
  return SCREENS.filter((screen) => isVisibleTo(screen, roles, tenantKind));
}

export function isVisibleTo(
  screen: Screen,
  roles: readonly Role[] | null,
  tenantKind?: TenantKind,
): boolean {
  if (screen.roles === "public") return true;
  if (roles === null) return false;
  if (
    tenantKind !== undefined &&
    screen.tenantKinds !== undefined &&
    !screen.tenantKinds.includes(tenantKind)
  ) {
    return false;
  }
  return screen.roles.some((role) => roles.includes(role));
}
