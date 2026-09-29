"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { AppShell } from "@compliancewatch/ui";
import type { NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { activeHref } from "@/shared/lib/url";
import { RouterLink } from "./router-link";

export interface TenantShellProps {
  /** Header links; the active one is worked out here from the current pathname. */
  items: readonly NavLink[];
  userMenu?: ReactNode;
  children: ReactNode;
}

/** The public and tenant shell: AppShell over next/link, with the current link marked. */
export function TenantShell({ items, userMenu, children }: TenantShellProps) {
  const current = activeHref(
    items.map((item) => item.href),
    usePathname(),
  );
  const navItems = items.map((item) => ({
    href: item.href,
    label: item.label,
    active: item.href === current,
  }));
  return (
    <AppShell
      items={navItems}
      userMenu={userMenu}
      Link={RouterLink}
      productName={t("common.appName")}
      navLabel={t("nav.primary")}
    >
      {children}
    </AppShell>
  );
}
