import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function ProfileReviewTasksLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-5xl">
      <Skeleton className="h-4 w-56" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-16 w-full max-w-4xl" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-64 w-full" />
    </SkeletonGroup>
  );
}
