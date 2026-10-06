import { PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { DryRunForm, type DryRunAction } from "./dry-run-form";
import type { DryRunFormValues } from "./dry-run-shared";

export interface ImpactViewProps {
  title: string;
  crumbs: readonly Crumb[];
  action: DryRunAction;
  initial: DryRunFormValues;
}

/**
 * The impact explorer: what a rule version (in any status) or a specification would decide for
 * the business directory before it fans out. The engine evaluates it as a fan-out would, stores no
 * decision and sends nothing; it writes one audit entry with the admin and the counts. An admin
 * tool, as the engine's route is: a dry run reads every tenant's profiles.
 */
export function ImpactView({ title, crumbs, action, initial }: ImpactViewProps) {
  return (
    <div data-slot="impact-explorer" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("impact.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <p className="max-w-prose text-sm text-fg-muted">{t("impact.stores")}</p>
      <DryRunForm action={action} initial={initial} />
    </div>
  );
}
