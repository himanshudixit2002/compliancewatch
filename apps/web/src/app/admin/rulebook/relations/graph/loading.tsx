import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function RelationsGraphLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-6xl">
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-16 w-full max-w-4xl" />
      <Skeleton className="h-72 w-full" />
    </SkeletonGroup>
  );
}
