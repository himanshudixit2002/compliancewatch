import { KeyValue, PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import type { DocumentView as DocumentViewModel, HeaderItem } from "../model/document-view";
import { ClauseList } from "./clause-list";
import { HighlightNote } from "./highlight-note";
import { JumpToClause } from "./jump-to-clause";
import { ScrollToMarked } from "./scroll-to-marked";

export interface DocumentViewProps {
  view: DocumentViewModel;
  crumbs: readonly Crumb[];
}

function headerValue(item: HeaderItem) {
  if (item.href !== undefined) {
    return (
      <a
        href={item.href}
        target="_blank"
        rel="noopener noreferrer"
        className="break-all text-primary underline"
      >
        {item.value}
        <span className="sr-only"> {t("documents.opensInNewTab")}</span>
      </a>
    );
  }
  if (item.copy !== undefined) {
    return <code className="font-mono text-xs break-all">{item.value}</code>;
  }
  return item.value;
}

/**
 * One rulebook document as the rulebook holds it: the title and the facts about the source,
 * then every clause in reading order with its reference, page and anchor, a jump to any clause,
 * and the span or clause a link asked to mark with a note on what was marked.
 */
export function DocumentView({ view, crumbs }: DocumentViewProps) {
  return (
    <div data-slot="document-view" className="flex max-w-4xl flex-col gap-6">
      <PageHeader
        title={view.title}
        description={t("documents.view.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <HighlightNote highlight={view.highlight} />
      <section aria-labelledby="document-facts" className="flex flex-col gap-3">
        <h2 id="document-facts" className="text-lg font-semibold text-fg">
          {t("documents.view.facts")}
        </h2>
        <KeyValue
          items={view.header.map((item) => ({
            key: item.key,
            label: item.label,
            value: headerValue(item),
            ...(item.copy === undefined
              ? {}
              : { copy: item.copy, copyLabel: t("documents.copy", { label: item.label }) }),
          }))}
        />
      </section>
      <section aria-labelledby="document-clauses" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="document-clauses" className="text-lg font-semibold text-fg">
            {t("documents.view.clauses", { count: view.clauses.length })}
          </h2>
          <JumpToClause
            options={view.clauses.map((clause) => ({
              anchorId: clause.anchorId,
              label:
                clause.page === null
                  ? clause.clauseRef
                  : t("documents.jump.option", { ref: clause.clauseRef, page: clause.page }),
            }))}
          />
        </div>
        {view.clauses.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("documents.view.noClauses")}</p>
        ) : (
          <ClauseList clauses={view.clauses} />
        )}
      </section>
      {view.markedAnchorId === null ? null : <ScrollToMarked anchorId={view.markedAnchorId} />}
    </div>
  );
}
