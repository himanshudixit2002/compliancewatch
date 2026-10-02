import type { ReactNode } from "react";
import { PageHeader } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "./breadcrumbs";
import { SectionNav } from "./section-nav";

export interface SettingsHeaderProps {
  title: string;
  description?: ReactNode;
  /** Settings, then the page (nav.ts's settingsHeaderLinks). */
  crumbs: readonly Crumb[];
  /** The settings pages the session may open, for the row of tabs. */
  tabs: readonly NavLink[];
}

/** The top of every settings page: breadcrumbs back to Settings, the one h1, and the tabs. */
export function SettingsHeader({ title, description, crumbs, tabs }: SettingsHeaderProps) {
  return (
    <div data-slot="settings-header" className="flex flex-col gap-4">
      <PageHeader
        title={title}
        description={description}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <SectionNav items={tabs} label={t("settings.tabs")} />
    </div>
  );
}
