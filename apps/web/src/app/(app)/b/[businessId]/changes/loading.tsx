import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function ChangesLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-4xl">
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-48 w-full" />
      <Skeleton className="h-48 w-full" />
    </SkeletonGroup>
  );
}
