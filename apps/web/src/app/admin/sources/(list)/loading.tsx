import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function SourcesLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-7xl">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-96 w-full" />
    </SkeletonGroup>
  );
}
