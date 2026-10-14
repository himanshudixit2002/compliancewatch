import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function TeamLoading() {
  return (
    <SkeletonGroup label={t("common.loading")}>
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-4 w-80" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-64 w-full" />
    </SkeletonGroup>
  );
}
