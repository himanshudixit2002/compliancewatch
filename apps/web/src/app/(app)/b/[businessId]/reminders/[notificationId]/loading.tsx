import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function ReminderLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-4xl">
      <Skeleton className="h-4 w-72" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-72 w-full" />
    </SkeletonGroup>
  );
}
