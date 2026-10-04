import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

// In a route group so it wraps the console alone, not the notification and template pages.
export default function AdminNotificationsLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-5xl">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-16 w-full max-w-3xl" />
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-64 w-full" />
    </SkeletonGroup>
  );
}
