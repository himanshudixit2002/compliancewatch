import { NotFoundView } from "@/features/system-pages";
import { publicNav } from "@/shared/config/nav";
import { TenantShell } from "@/shared/ui/tenant-shell";

// Rendered for notFound() anywhere below the root layout, so it brings its own shell.
export default function NotFound() {
  return (
    <TenantShell items={publicNav()}>
      <NotFoundView />
    </TenantShell>
  );
}
