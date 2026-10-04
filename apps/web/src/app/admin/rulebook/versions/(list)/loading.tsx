import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

// In a route group so it wraps the list alone, not a version's page.
export default function RuleVersionsLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-6xl">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-8 w-full max-w-3xl" />
      <Skeleton className="h-16 w-full max-w-2xl" />
      <Skeleton className="h-96 w-full" />
    </SkeletonGroup>
  );
}
