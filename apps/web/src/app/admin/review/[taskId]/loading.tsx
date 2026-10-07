import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function ReviewWorkbenchLoading() {
  return (
    <SkeletonGroup label={t("common.loading")}>
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-8 w-80" />
      <Skeleton className="h-24 w-full max-w-3xl" />
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <Skeleton className="h-96 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
      <Skeleton className="h-48 w-full" />
    </SkeletonGroup>
  );
}
