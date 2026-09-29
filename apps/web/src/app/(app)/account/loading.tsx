import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function AccountLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-2xl">
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-4 w-80" />
      <Skeleton className="h-40 w-full" />
    </SkeletonGroup>
  );
}
