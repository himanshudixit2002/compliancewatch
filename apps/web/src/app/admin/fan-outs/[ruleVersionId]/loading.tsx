import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function FanOutLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-5xl">
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-8 w-80" />
      <Skeleton className="h-12 w-full max-w-3xl" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-24 w-full max-w-2xl" />
      <Skeleton className="h-32 w-full" />
    </SkeletonGroup>
  );
}
