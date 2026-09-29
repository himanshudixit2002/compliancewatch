import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function SettingsLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-4xl">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </SkeletonGroup>
  );
}
