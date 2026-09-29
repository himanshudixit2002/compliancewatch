import { PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { OpenDocumentForm, type OpenDocumentAction } from "./open-document-form";

export interface DocumentsOpenViewProps {
  title: string;
  crumbs: readonly Crumb[];
  action: OpenDocumentAction;
  field: string;
}

/**
 * The documents tool before a list exists: open one document by its id or its sha256. The note
 * says where a list will come from, so nobody looks for one here.
 */
export function DocumentsOpenView({ title, crumbs, action, field }: DocumentsOpenViewProps) {
  return (
    <div data-slot="documents-open" className="flex max-w-3xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("documents.open.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <OpenDocumentForm action={action} field={field} />
      <p className="max-w-prose text-sm text-fg-muted">{t("documents.open.noList")}</p>
    </div>
  );
}
