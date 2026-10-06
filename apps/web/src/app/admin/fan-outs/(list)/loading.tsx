import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

// In a route group so it wraps the list alone, not a version's fan-out page.
export default function FanOutsLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-5xl">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-12 w-full max-w-3xl" />
      <Skeleton className="h-64 w-full" />
    </SkeletonGroup>
  );
}
