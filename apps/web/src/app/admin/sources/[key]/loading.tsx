import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function SourceLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-6xl">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-48 w-full" />
      <Skeleton className="h-32 w-full max-w-2xl" />
      <Skeleton className="h-72 w-full" />
    </SkeletonGroup>
  );
}
