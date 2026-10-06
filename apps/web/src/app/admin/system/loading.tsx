import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function SystemLoading() {
  return (
    <SkeletonGroup label={t("common.loading")}>
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <div className="grid gap-3 sm:grid-cols-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
      <Skeleton className="h-96 w-full" />
    </SkeletonGroup>
  );
}
