import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function CalendarLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-3xl">
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-80 w-full" />
    </SkeletonGroup>
  );
}
