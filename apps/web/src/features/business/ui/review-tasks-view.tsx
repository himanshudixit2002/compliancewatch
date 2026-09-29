import { EmptyState } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { ReviewTasksView as ReviewTasksViewModel } from "../model/business-pages";
import { BusinessPageHeader, type BusinessPageHeaderProps } from "./business-page-header";
import { ReviewTasksTable } from "./review-tasks-table";

export interface ReviewTasksViewProps {
  title: string;
  view: ReviewTasksViewModel;
  header: Omit<BusinessPageHeaderProps, "title" | "description">;
}

/**
 * The review tasks on the business and its registrations, open first: why each is open, the
 * year, when, and the node. Resolving one is an analyst's action; no route for it exists yet.
 */
export function ReviewTasksView({ title, view, header }: ReviewTasksViewProps) {
  return (
    <div data-slot="review-tasks-view" className="flex max-w-5xl flex-col gap-6">
      <BusinessPageHeader
        {...header}
        title={title}
        description={t("business.pageIntro", { name: view.header.name, pan: view.header.pan })}
      />
      <p className="max-w-prose text-sm text-fg-muted">{t("reviewTasks.intro")}</p>
      {view.rows.length === 0 ? (
        <EmptyState title={t("reviewTasks.emptyTitle")} body={t("reviewTasks.emptyBody")} />
      ) : (
        <>
          <p className="text-sm text-fg" data-slot="review-tasks-count">
            {t("reviewTasks.openCount", { count: view.openCount, total: view.rows.length })}
          </p>
          <ReviewTasksTable rows={view.rows} caption={t("reviewTasks.caption")} showStatus />
        </>
      )}
    </div>
  );
}
