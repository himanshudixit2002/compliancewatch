import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function NotificationRecipientsLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-5xl">
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-8 w-72" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-10 w-80" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-72 w-full max-w-2xl" />
    </SkeletonGroup>
  );
}
