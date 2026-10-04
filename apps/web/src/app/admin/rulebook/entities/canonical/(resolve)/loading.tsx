import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

// In a route group so it wraps the resolve tool alone, not an entity's page.
export default function CanonicalEntitiesLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-4xl">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-16 w-full max-w-3xl" />
      <Skeleton className="h-40 w-full" />
    </SkeletonGroup>
  );
}
