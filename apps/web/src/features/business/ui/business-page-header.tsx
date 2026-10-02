import type { ReactNode } from "react";
import { PageHeader } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { SectionNav } from "@/shared/ui/section-nav";

export interface BusinessPageHeaderProps {
  title: string;
  description?: ReactNode;
  /** The parent chain, root first; the business's crumb carries its name. */
  crumbs: readonly Crumb[];
  /** The business's pages from the registry, for the row of tabs. */
  tabs: readonly NavLink[];
  actions?: ReactNode;
}

/** The top of every business page: breadcrumbs, the one h1, and the business's pages. */
export function BusinessPageHeader({
  title,
  description,
  crumbs,
  tabs,
  actions,
}: BusinessPageHeaderProps) {
  return (
    <div data-slot="business-page-header" className="flex flex-col gap-4">
      <PageHeader
        title={title}
        description={description}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={actions}
      />
      <SectionNav items={tabs} label={t("business.tabs")} />
    </div>
  );
}
