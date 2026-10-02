import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function OnboardingDoneLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-3xl">
      <Skeleton className="h-6 w-80" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-32 w-full" />
    </SkeletonGroup>
  );
}
