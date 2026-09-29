import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Button } from "@compliancewatch/ui";
import { publicNav } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { TenantShell } from "@/shared/ui/tenant-shell";

// Tenant screens. No session exists yet, so the shell shows the visitor links; the session
// package reads the cookie here and passes the tenant navigation and the account menu.
export default function AppLayout({ children }: Readonly<{ children: ReactNode }>) {
  const signIn = hrefFor(screenById("system.sign-in"));
  return (
    <TenantShell
      items={publicNav()}
      userMenu={
        <Button asChild variant="secondary" size="sm">
          <Link href={signIn as Route}>{t("common.signIn")}</Link>
        </Button>
      }
    >
      {children}
    </TenantShell>
  );
}
