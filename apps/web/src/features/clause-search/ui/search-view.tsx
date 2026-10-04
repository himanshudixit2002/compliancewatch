import { PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { documentTypeOptions, hitCountOptions } from "../model/search-form";
import { SearchForm, type SearchAction } from "./search-form";

export interface SearchViewProps {
  title: string;
  crumbs: readonly Crumb[];
  action: SearchAction;
}

/**
 * The clause search tool: what the rulebook's hybrid search finds for some words, each hit with
 * the rank of each leg and the fused score. The page says that it sends the words alone, so the
 * vector leg does not run from here.
 */
export function SearchView({ title, crumbs, action }: SearchViewProps) {
  return (
    <div data-slot="search-tool" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("search.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <p className="max-w-prose text-sm text-fg-muted">{t("search.legs")}</p>
      <SearchForm action={action} docTypes={documentTypeOptions()} counts={hitCountOptions()} />
    </div>
  );
}
