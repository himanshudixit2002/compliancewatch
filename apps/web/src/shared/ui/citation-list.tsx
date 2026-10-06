import { Badge } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

/** A cited clause, worded for the list: the services' facts, nothing decided here. */
export interface CitationView {
  id: string;
  clauseRef: string;
  /** The verified quote, as the rulebook stored it. */
  quote: string;
  /** The whole clause as the rulebook holds it; null when it could not be read. */
  clauseText: string | null;
  documentTitle: string | null;
  /** The document's reference (a notification number); null when unread. */
  documentRef: string | null;
  /** The regulator's source document, an http(s) link only; null otherwise. */
  sourceHref: string | null;
  page: number | null;
  /** When the quote was checked against the clause, worded; null when the service gives no date. */
  verifiedAt: string | null;
}

export interface CitationListProps {
  citations: readonly CitationView[];
  /** What to say when there is none. */
  empty: string;
}

/**
 * The clauses an obligation, a change or an answer cites: the reference and the document, the
 * verified quote as the rulebook stored it (never paraphrased), the whole clause on request, and
 * the regulator's source document to check it against. Only the services' quotes reach this list,
 * and each was checked against its clause before it was returned.
 */
export function CitationList({ citations, empty }: CitationListProps) {
  if (citations.length === 0) return <p className="text-sm text-fg-muted">{empty}</p>;
  return (
    <ul className="flex flex-col gap-3" data-slot="citation-list">
      {citations.map((citation) => (
        <li
          key={citation.id}
          data-citation={citation.clauseRef}
          className="flex flex-col gap-2 rounded-md border border-line bg-surface-raised p-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="font-medium text-fg">
              {citation.documentTitle === null
                ? t("citation.clauseOnly", { ref: citation.clauseRef })
                : t("citation.clauseOf", {
                    ref: citation.clauseRef,
                    document:
                      citation.documentRef === null || citation.documentRef === ""
                        ? citation.documentTitle
                        : `${citation.documentTitle} (${citation.documentRef})`,
                  })}
            </span>
            <Badge tone="success">
              {citation.verifiedAt === null
                ? t("citation.verified")
                : t("citation.verifiedOn", { date: citation.verifiedAt })}
            </Badge>
          </div>
          <blockquote className="border-l-4 border-line-strong pl-3 text-sm text-fg whitespace-pre-wrap">
            {citation.quote}
          </blockquote>
          {citation.clauseText === null ? (
            <p className="text-xs text-fg-muted">{t("citation.clauseUnread")}</p>
          ) : (
            <details className="text-sm">
              <summary className="cursor-pointer text-primary">
                {citation.page === null
                  ? t("citation.wholeClause")
                  : t("citation.wholeClausePage", { page: citation.page })}
              </summary>
              <p className="mt-2 whitespace-pre-wrap text-fg" data-slot="clause-text">
                {citation.clauseText}
              </p>
            </details>
          )}
          {citation.sourceHref === null ? null : (
            <p className="text-sm">
              <a
                href={citation.sourceHref}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline-offset-2 hover:underline"
              >
                {t("citation.source")}
                <span className="sr-only"> {t("citation.newTab")}</span>
              </a>
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
