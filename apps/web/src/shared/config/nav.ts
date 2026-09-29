import type { FlagName } from "./flags.ts";
import { isRegulatory } from "./roles.ts";
import type { Principal, Role, TenantKind } from "./roles.ts";
import { isActivePath, safeNext, withQuery } from "../lib/url.ts";
import { SCREENS, hrefFor, isVisibleTo, routeParams, screenById } from "./screens.ts";
import type { Screen, ScreenId } from "./screens.ts";

/**
 * Navigation derived from the registry: the app shell's groups for tenant users, the admin
 * shell's grouped tools, and breadcrumbs from the parent chain. Entries are filtered by the
 * session's roles and tenant kind, by their flag, and by whether their route parameters are
 * known (a business-scoped link needs the current businessId).
 */
export interface NavLink {
  id: string;
  href: string;
  label: string;
  active?: boolean;
}

export interface NavSection {
  key: string;
  label: string;
  items: NavLink[];
}

export interface NavContext {
  /** null for an anonymous visitor. */
  roles: readonly Role[] | null;
  tenantKind?: TenantKind;
  /** Route parameters known on this request, for example { businessId }. */
  params?: Readonly<Record<string, string>>;
  /** The server-side flag reader; when absent every flagged entry is hidden. */
  isFlagEnabled?: (flag: FlagName) => boolean;
  currentPath?: string;
}

/** Group keys in display order with their labels, for the tenant shell and the admin shell. */
export const NAV_GROUPS = {
  business: "Your business",
  clients: "Clients",
  settings: "Settings",
  account: "Account",
  rulebook: "Rulebook",
  review: "Review",
  operations: "Operations",
  engine: "Applicability",
  evals: "Evals",
  identity: "Tenants and users",
} as const;

export type NavGroupKey = keyof typeof NAV_GROUPS;

const APP_GROUPS: readonly NavGroupKey[] = ["business", "clients", "settings", "account"];
const ADMIN_GROUPS: readonly NavGroupKey[] = [
  "rulebook",
  "review",
  "operations",
  "engine",
  "evals",
  "identity",
];

export function isNavGroupKey(value: string): value is NavGroupKey {
  return value in NAV_GROUPS;
}

function hasParams(screen: Screen, params: Readonly<Record<string, string>>): boolean {
  return routeParams(screen.route).every((name) => params[name] !== undefined);
}

function flagAllows(screen: Screen, ctx: NavContext): boolean {
  if (screen.flag === undefined) return true;
  return ctx.isFlagEnabled?.(screen.flag) ?? false;
}

function toLink(screen: Screen, ctx: NavContext): NavLink {
  const href = hrefFor(screen, ctx.params ?? {});
  const link: NavLink = { id: screen.id, href, label: screen.title };
  if (ctx.currentPath !== undefined && isActive(href, ctx.currentPath)) link.active = true;
  return link;
}

/** A link is active on its own path and on paths below it, except the home links. */
export function isActive(href: string, currentPath: string): boolean {
  return isActivePath(href, currentPath);
}

/** The screens every visitor can open from the header: the home page and the sitemap. */
const PUBLIC_NAV_IDS: readonly ScreenId[] = ["system.home", "system.sitemap"];

/** The header links for a visitor without a session (and above the tenant groups with one). */
export function publicNav(currentPath?: string): NavLink[] {
  const ctx: NavContext = { roles: null };
  if (currentPath !== undefined) ctx.currentPath = currentPath;
  return PUBLIC_NAV_IDS.map((id) => toLink(screenById(id), ctx));
}

/** Where a session lands after signing in: the internal tools, or the businesses list. */
export function homeFor(principal: Principal): string {
  return isRegulatory(principal)
    ? hrefFor(screenById("admin.home"))
    : hrefFor(screenById("owner.businesses"));
}

/**
 * The sign-in page, with `next` when it is a same-origin path worth returning to (the root
 * and the sign-in page itself are not).
 */
export function signInHref(next?: string): string {
  const signIn = hrefFor(screenById("system.sign-in"));
  const safe = safeNext(next, "");
  if (safe === "" || safe === "/" || safe === signIn || safe.startsWith(`${signIn}?`)) {
    return signIn;
  }
  return withQuery(signIn, { next: safe });
}

export function forbiddenHref(): string {
  return hrefFor(screenById("system.forbidden"));
}

function sectionsFor(
  groups: readonly NavGroupKey[],
  ctx: NavContext,
  screens: readonly Screen[],
): NavSection[] {
  const params = ctx.params ?? {};
  return groups
    .map((key) => {
      const items = screens
        .filter(
          (screen) =>
            screen.nav?.group === key &&
            screen.kind === "page" &&
            isVisibleTo(screen, ctx.roles, ctx.tenantKind) &&
            flagAllows(screen, ctx) &&
            hasParams(screen, params),
        )
        .sort((a, b) => (a.nav?.order ?? 0) - (b.nav?.order ?? 0))
        .map((screen) => toLink(screen, ctx));
      return { key, label: NAV_GROUPS[key], items };
    })
    .filter((section) => section.items.length > 0);
}

/** The tenant shell's navigation: business, clients, settings and account groups. */
export function navFor(ctx: NavContext, screens: readonly Screen[] = SCREENS): NavSection[] {
  return sectionsFor(APP_GROUPS, ctx, screens);
}

/**
 * The pages of one business, for the tabs above them: the business group's entries whose route
 * is under /b/[businessId], in their nav order. Empty until the businessId is known.
 */
export function businessNavFor(ctx: NavContext, screens: readonly Screen[] = SCREENS): NavLink[] {
  const section = sectionsFor(["business"], ctx, screens)[0];
  return (section?.items ?? []).filter((item) => {
    const screen = screens.find((candidate) => candidate.id === item.id);
    return screen?.route.startsWith("/b/[businessId]") ?? false;
  });
}

/**
 * The settings pages for the tabs above them: the settings group's entries the session may
 * open, in their nav order, without the planned ones (the settings index lists those with their
 * status, and a tab should lead somewhere that exists or is coming).
 */
export function settingsNavFor(ctx: NavContext, screens: readonly Screen[] = SCREENS): NavLink[] {
  const coming = screens.filter((screen) => screen.status !== "planned");
  return sectionsFor(["settings"], ctx, coming)[0]?.items ?? [];
}

/** What a settings page's header needs: the breadcrumbs up to Settings and the tabs. */
export function settingsHeaderLinks(
  screen: Screen,
  principal: { roles: readonly Role[]; tenantKind: TenantKind },
): { crumbs: Crumb[]; tabs: NavLink[] } {
  return {
    crumbs: breadcrumbsFor(screen.id as ScreenId),
    tabs: settingsNavFor({ roles: principal.roles, tenantKind: principal.tenantKind }),
  };
}

/** The admin shell's grouped tools; empty for a non-regulatory session. */
export function adminNavFor(ctx: NavContext, screens: readonly Screen[] = SCREENS): NavSection[] {
  return sectionsFor(ADMIN_GROUPS, ctx, screens);
}

export interface Crumb {
  id: string;
  href: string;
  label: string;
}

/** The parent chain of a screen, root first, ending with the screen itself. */
export function breadcrumbsFor(
  id: ScreenId,
  params: Readonly<Record<string, string>> = {},
): Crumb[] {
  const chain: Screen[] = [];
  let current: Screen | undefined = screenById(id);
  while (current !== undefined) {
    if (chain.includes(current)) throw new Error(`breadcrumb cycle at ${current.id}`);
    chain.unshift(current);
    current = current.parent === undefined ? undefined : screenById(current.parent as ScreenId);
  }
  return chain.map((screen) => ({
    id: screen.id,
    href: hrefFor(screen, params),
    label: screen.title,
  }));
}
