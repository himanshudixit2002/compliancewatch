import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function OnboardingBusinessLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-3xl">
      <Skeleton className="h-6 w-80" />
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-10 w-full max-w-xl" />
      <Skeleton className="h-10 w-full max-w-xl" />
      <Skeleton className="h-10 w-40" />
    </SkeletonGroup>
  );
}
