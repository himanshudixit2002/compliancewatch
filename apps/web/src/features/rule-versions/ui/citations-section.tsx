import type { Route } from "next";
import Link from "next/link";
import {
  Banner,
  EmptyState,
  HighlightMark,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { ServiceError } from "@/shared/ui/service-error";
import type { CitationView, Part } from "../model/version-page";
import type { AccessView } from "./workflow-shared";
import { CitationsEditor, type SaveCitationsAction } from "./citations-editor";

export interface CitationsSectionProps {
  citations: Part<readonly CitationView[]>;
  canCite: boolean;
  access: AccessView;
  action: SaveCitationsAction;
}

function ClauseText({ view }: { view: CitationView }) {
  if (view.clause === null) {
    return <p className="text-xs text-fg-muted">{t("citations.clauseUnread")}</p>;
  }
  return (
    <details className="text-sm" data-slot="citation-clause">
      <summary className="cursor-pointer text-primary">{t("citations.clauseText")}</summary>
      <p className="mt-2 whitespace-pre-wrap text-fg">
        {view.quoteMark === null ? (
          view.clause.text
        ) : (
          <>
            {view.quoteMark.before}
            <HighlightMark startLabel={t("citations.markStart")} endLabel={t("citations.markEnd")}>
              {view.quoteMark.mark}
            </HighlightMark>
            {view.quoteMark.after}
          </>
        )}
      </p>
    </details>
  );
}

/**
 * The clauses a version rests on, each with its quote and the rulebook's verification, and, for
 * a draft, the form that cites more. A published version is published only with at least one
 * citation, every one verified (ADR-006), so the empty state says so.
 */
export function CitationsSection({ citations, canCite, access, action }: CitationsSectionProps) {
  return (
    <section aria-labelledby="version-citations" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="version-citations" className="text-lg font-semibold text-fg">
          {t("citations.heading")}
        </h2>
        <p className="max-w-prose text-sm text-fg-muted">{t("citations.intro")}</p>
      </div>
      {!citations.ok ? (
        <ServiceError error={citations.error} />
      ) : citations.value.length === 0 ? (
        <EmptyState
          heading="h3"
          title={t("citations.emptyTitle")}
          body={t("citations.emptyBody")}
        />
      ) : (
        <Table data-slot="citations-table" scrollLabel={t("citations.tableRegion")}>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("citations.caption", { count: citations.value.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("citations.column.clause")}</TableHead>
              <TableHead>{t("citations.column.quote")}</TableHead>
              <TableHead>{t("citations.column.verification")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {citations.value.map((view) => (
              <TableRow
                key={view.citation.citationId}
                data-citation={view.citation.citationId}
                data-clause-ref={view.citation.clauseRef}
              >
                <TableCell className="align-top">
                  <div className="flex flex-col gap-1">
                    <Link
                      href={view.clauseHref as Route}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {t("citations.clauseLink", { ref: view.citation.clauseRef })}
                    </Link>
                    {view.clause === null ? null : (
                      <span className="text-xs text-fg-muted">
                        {view.clause.externalRef}: {view.clause.title}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="max-w-md align-top">
                  <div className="flex flex-col gap-2">
                    <blockquote className="border-l-2 border-line-strong pl-3 text-sm whitespace-pre-wrap text-fg">
                      {view.citation.quote}
                    </blockquote>
                    <ClauseText view={view} />
                  </div>
                </TableCell>
                <TableCell className="align-top">
                  <div className="flex flex-col items-start gap-1 text-sm">
                    <StatusChip
                      status={view.citation.verified ? "verified" : "not_verified"}
                      tone={view.citation.verified ? "success" : "danger"}
                      label={
                        view.citation.verified
                          ? t("citations.verified")
                          : t("citations.notVerified")
                      }
                    />
                    {view.citation.matchScore === null ? null : (
                      <span>
                        {t("citations.score", { score: view.citation.matchScore.toFixed(2) })}
                      </span>
                    )}
                    {view.citation.verifiedAt === null ? null : (
                      <span className="text-fg-muted">
                        {formatDateTime(view.citation.verifiedAt)}
                      </span>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {!canCite ? (
        <p className="max-w-prose text-sm text-fg-muted">{t("citations.draftOnly")}</p>
      ) : access.allowed ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-base font-semibold text-fg">{t("citations.form.heading")}</h3>
          <p className="max-w-prose text-sm text-fg-muted">{t("citations.form.intro")}</p>
          <CitationsEditor action={action} />
        </div>
      ) : (
        <Banner tone="warning" title={t("citations.heldBack")}>
          {access.title}
          {access.detail === undefined ? null : <span className="block">{access.detail}</span>}
        </Banner>
      )}
    </section>
  );
}
