import { EmptyState, PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import type { RuleRow } from "./rules-shared";
import { RulesTable } from "./rules-table";

export interface RulesViewProps {
  title: string;
  crumbs: readonly Crumb[];
  rows: readonly RuleRow[];
}

/**
 * Every rule the rulebook holds, by key, with its regulator, the title of its latest version and
 * a way to all its versions. The list is read-only: a rule arrives with its first version (the
 * seed command, or a draft made from a rule candidate).
 */
export function RulesView({ title, crumbs, rows }: RulesViewProps) {
  return (
    <div data-slot="rules" className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("rules.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      {rows.length === 0 ? (
        <EmptyState title={t("rules.emptyTitle")} body={t("rules.emptyBody")} />
      ) : (
        <RulesTable rows={rows} />
      )}
    </div>
  );
}
