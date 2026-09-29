import type { ReactNode } from "react";
import { toSessionDto } from "@/entities/session/mappers";
import { requireAdmin } from "@/server/dal";
import { webEnvName } from "@/server/env";
import { adminNavFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { InternalShell } from "@/shared/ui/internal-shell";
import { SessionMenu } from "@/shared/ui/session-menu";

// The session and the environment label are read per request, never baked in at build time.
export const dynamic = "force-dynamic";

// The shell lists the tools the session's roles may open. requireAdmin here is the outer
// wall (a tenant role gets the 404 before any admin markup exists); every admin page and
// action calls it again, because a layout is not re-run on every navigation.
export default async function AdminLayout({ children }: Readonly<{ children: ReactNode }>) {
  const session = await requireAdmin({ next: hrefFor(screenById("admin.home")) });
  const groups = adminNavFor({ roles: session.roles, tenantKind: session.tenantKind });
  return (
    <InternalShell
      groups={groups}
      environment={webEnvName()}
      userMenu={<SessionMenu session={toSessionDto(session)} />}
    >
      {children}
    </InternalShell>
  );
}
