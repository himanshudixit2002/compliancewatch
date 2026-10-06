import type { FlagName } from "@/shared/config/flags";
import { breadcrumbsFor, businessNavFor, type Crumb, type NavLink } from "@/shared/config/nav";
import type { Role, TenantKind } from "@/shared/config/roles";
import {
  SCREENS,
  hrefFor,
  isVisibleTo,
  routeParams,
  type Screen,
  type ScreenId,
} from "@/shared/config/screens";
import type { ScreenStatus } from "@/shared/ui/screen-status-chip";

/**
 * Where a business page sits, from the screen registry: its breadcrumbs (the business's crumb
 * named after the business rather than "Business"), the row of the business's pages, and the
 * business's screens that are not built yet, for the home page.
 */
export interface BusinessViewer {
  roles: readonly Role[];
  tenantKind: TenantKind;
}

export interface BusinessHeaderLinks {
  crumbs: Crumb[];
  tabs: NavLink[];
}

const HOME_ID = "owner.business";

const NO_FLAGS: ReadonlySet<FlagName> = new Set();

/**
 * The breadcrumbs and the tabs of a business page. A page behind a flag (Ask) has a tab only
 * when its flag is on for the session's tenant: `flags` is the set `businessFlags` read.
 */
export function businessHeaderLinks(
  screenId: ScreenId,
  viewer: BusinessViewer,
  businessId: string,
  businessName: string,
  flags: ReadonlySet<FlagName> = NO_FLAGS,
): BusinessHeaderLinks {
  const params = { businessId };
  return {
    crumbs: breadcrumbsFor(screenId, params).map((crumb) =>
      crumb.id === HOME_ID ? { ...crumb, label: businessName } : crumb,
    ),
    tabs: businessNavFor({
      roles: viewer.roles,
      tenantKind: viewer.tenantKind,
      params,
      isFlagEnabled: (flag) => flags.has(flag),
    }),
  };
}

export interface LaterScreenLink {
  id: string;
  title: string;
  status: ScreenStatus;
  href: string;
}

/** The business's pages that are not live, which the viewer may open, with their notices. */
export function laterScreens(
  viewer: BusinessViewer,
  businessId: string,
  screens: readonly Screen[] = SCREENS,
): LaterScreenLink[] {
  return screens
    .filter(
      (screen) =>
        screen.kind === "page" &&
        screen.status !== "live" &&
        screen.route.startsWith("/b/[businessId]/") &&
        routeParams(screen.route).length === 1 &&
        isVisibleTo(screen, viewer.roles, viewer.tenantKind),
    )
    .map((screen) => ({
      id: screen.id,
      title: screen.title,
      status: screen.status,
      href: hrefFor(screen, { businessId }),
    }));
}
