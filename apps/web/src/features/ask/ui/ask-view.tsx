import { EmptyState, PageHeader } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { NotLegalAdvice } from "@/shared/ui/not-legal-advice";
import { SectionNav } from "@/shared/ui/section-nav";
import type { AskPageView } from "../queries";
import { AskForm, type AskAction } from "./ask-form";

export interface AskViewProps {
  title: string;
  view: AskPageView;
  header: { crumbs: readonly Crumb[]; tabs: readonly NavLink[] };
  action: AskAction;
}

/**
 * Ask a question about the business. While `web.qa_enabled` is off for the tenant the page says
 * so and offers no form; on, the form asks the public API and shows its answer with the layer
 * that decided and the citations, or that the question is not covered.
 */
export function AskView({ title, view, header, action }: AskViewProps) {
  return (
    <div data-slot="ask-page" className="flex max-w-3xl flex-col gap-6">
      <div className="flex flex-col gap-4">
        <PageHeader
          title={title}
          description={t("business.pageIntro", {
            name: view.business.name,
            pan: view.business.pan,
          })}
          breadcrumbs={<Breadcrumbs crumbs={header.crumbs} />}
        />
        <SectionNav items={header.tabs} label={t("business.tabs")} />
      </div>
      {view.enabled ? (
        <>
          <p className="max-w-prose text-sm text-fg-muted">{t("ask.intro")}</p>
          <AskForm action={action} businessId={view.business.id} nodes={view.nodes} />
        </>
      ) : (
        <EmptyState title={t("ask.off.title")} body={t("ask.off.body")} />
      )}
      <NotLegalAdvice />
    </div>
  );
}
