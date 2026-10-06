import { Skeleton, SkeletonGroup } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export default function RelationCandidatesLoading() {
  return (
    <SkeletonGroup label={t("common.loading")} className="max-w-6xl">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-full max-w-prose" />
      <Skeleton className="h-8 w-80" />
      <Skeleton className="h-10 w-full max-w-md" />
      <Skeleton className="h-96 w-full" />
    </SkeletonGroup>
  );
}
