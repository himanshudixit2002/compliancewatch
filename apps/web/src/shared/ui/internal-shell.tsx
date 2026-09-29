"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { AdminShell } from "@compliancewatch/ui";
import type { NavSection } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { activeHref } from "@/shared/lib/url";
import { RouterLink } from "./router-link";

export interface InternalShellProps {
  groups: readonly NavSection[];
  /** The runtime environment name shown in the internal banner. */
  environment: string;
  userMenu?: ReactNode;
  children: ReactNode;
}

/**
 * The /admin shell: AdminShell over next/link with the grouped tools and the active link. A tool
 * that is not built yet says so after its link ("Waiting", "Not built", "Not scheduled").
 */
export function InternalShell({ groups, environment, userMenu, children }: InternalShellProps) {
  const current = activeHref(
    groups.flatMap((group) => group.items.map((item) => item.href)),
    usePathname(),
  );
  const navGroups = groups.map((group) => ({
    label: group.label,
    items: group.items.map((item) => ({
      href: item.href,
      label: item.label,
      active: item.href === current,
      ...(item.status === undefined ? {} : { hint: t(`nav.status.${item.status}`) }),
    })),
  }));
  return (
    <AdminShell
      groups={navGroups}
      environment={environment}
      userMenu={userMenu}
      Link={RouterLink}
      productName={t("common.appName")}
    >
      {children}
    </AdminShell>
  );
}
