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

export function businessHeaderLinks(
  screenId: ScreenId,
  viewer: BusinessViewer,
  businessId: string,
  businessName: string,
): BusinessHeaderLinks {
  const params = { businessId };
  return {
    crumbs: breadcrumbsFor(screenId, params).map((crumb) =>
      crumb.id === HOME_ID ? { ...crumb, label: businessName } : crumb,
    ),
    tabs: businessNavFor({ roles: viewer.roles, tenantKind: viewer.tenantKind, params }),
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
