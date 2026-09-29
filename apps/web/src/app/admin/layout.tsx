import type { ReactNode } from "react";
import { adminNavFor } from "@/shared/config/nav";
import { REGULATORY_ROLES } from "@/shared/config/roles";
import { webEnvName } from "@/server/env";
import { InternalShell } from "@/shared/ui/internal-shell";

// The environment label is read per request, never baked in at build time.
export const dynamic = "force-dynamic";

// No session exists yet, so the sidebar lists every internal tool; the session package
// replaces the role set below with the session's roles behind requireAdmin().
export default function AdminLayout({ children }: Readonly<{ children: ReactNode }>) {
  const groups = adminNavFor({ roles: REGULATORY_ROLES, tenantKind: "internal" });
  return (
    <InternalShell groups={groups} environment={webEnvName()}>
      {children}
    </InternalShell>
  );
}
