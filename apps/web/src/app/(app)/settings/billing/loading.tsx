import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function BillingLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-4xl">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-48 w-full" />
    </SkeletonGroup>
  );
}
