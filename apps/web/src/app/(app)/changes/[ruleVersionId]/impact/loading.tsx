import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function ChangeImpactLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-5xl">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-20 w-full max-w-3xl" />
      <Skeleton className="h-64 w-full" />
      <Skeleton className="h-24 w-full max-w-2xl" />
    </SkeletonGroup>
  );
}
