import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Button } from "@compliancewatch/ui";
import { sessionForRender } from "@/server/dal";
import { navFor, publicNav } from "@/shared/config/nav";
import type { NavGroupKey, NavLink } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { SessionMenu } from "@/shared/ui/session-menu";
import { TenantShell } from "@/shared/ui/tenant-shell";

/** The tenant groups whose links fit the header; settings pages are reached from the sitemap. */
const HEADER_GROUPS: readonly NavGroupKey[] = ["business", "account"];

// Tenant screens: the shell reads the session for its links and the account menu; each page
// runs its own gate, so the layout only decides what to show, never whether to render.
export default async function AppLayout({ children }: Readonly<{ children: ReactNode }>) {
  const session = await sessionForRender();
  const items: NavLink[] = [...publicNav()];
  if (session !== null) {
    const groups = navFor({ roles: session.roles, tenantKind: session.tenantKind });
    for (const group of groups) {
      if (HEADER_GROUPS.includes(group.key as NavGroupKey)) items.push(...group.items);
    }
  }
  const signIn = hrefFor(screenById("system.sign-in"));
  return (
    <TenantShell
      items={items}
      userMenu={
        session === null ? (
          <Button asChild variant="secondary" size="sm">
            <Link href={signIn as Route}>{t("common.signIn")}</Link>
          </Button>
        ) : (
          <SessionMenu session={session} />
        )
      }
    >
      {children}
    </TenantShell>
  );
}
