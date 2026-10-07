import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  HighlightMark,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ServiceError } from "@/shared/ui/service-error";
import type { SourceClause, SourceDocument, SourcePane as SourcePaneModel } from "../model/source";

function ClauseText({ clause }: { clause: SourceClause }) {
  return (
    <>
      {clause.segments.map((segment, index) =>
        segment.mark ? (
          <HighlightMark
            key={index}
            startLabel={t("workbench.source.markStart")}
            endLabel={t("workbench.source.markEnd")}
          >
            {segment.text}
          </HighlightMark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}

function FileLink({ document }: { document: SourceDocument }) {
  const file = document.file;
  switch (file.kind) {
    case "stored":
      return (
        <a
          href={file.href}
          target="_blank"
          rel="noopener"
          className="text-sm text-primary underline-offset-2 hover:underline"
          data-slot="original-file"
        >
          {t("workbench.source.openFile", { type: file.type, size: file.size })}
          <span className="sr-only"> {t("workbench.source.newTab")}</span>
        </a>
      );
    case "none":
      return (
        <p className="text-sm text-fg-muted" data-slot="original-file-none">
          {t("workbench.source.noFile")}
        </p>
      );
    case "error":
      return (
        <div className="flex flex-col gap-1" data-slot="original-file-error">
          <p className="text-sm text-fg-muted">{t("workbench.source.fileUnread")}</p>
          <ServiceError error={file.error} />
        </div>
      );
  }
}

function DocumentSection({ document }: { document: SourceDocument }) {
  const headingId = `source-${document.documentId}`;
  return (
    <article
      aria-labelledby={headingId}
      data-slot="source-document"
      data-document={document.documentId}
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <div className="flex flex-col gap-1">
        <h3 id={headingId} className="text-base font-semibold text-fg">
          {document.title}
        </h3>
        <p className="text-sm text-fg-muted">
          {document.externalRef === ""
            ? document.facts
            : `${document.externalRef}, ${document.facts}`}
        </p>
        {document.role === "candidate" ? (
          <div>
            <Badge tone="info">{t("workbench.source.candidateDocument")}</Badge>
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <Link
          href={document.viewerHref as Route}
          className="text-sm text-primary underline-offset-2 hover:underline"
        >
          {t("workbench.source.viewer")}
        </Link>
        <FileLink document={document} />
      </div>
      {document.clausesError === null ? null : <ServiceError error={document.clausesError} />}
      {document.clauses === null ? null : document.clauses.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("workbench.source.noClauses")}</p>
      ) : (
        <div
          role="region"
          aria-label={t("workbench.source.clausesRegion", { title: document.title })}
          tabIndex={0}
          className="max-h-[36rem] overflow-y-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-focus/50"
        >
          <ol className="flex flex-col gap-3" data-slot="source-clauses">
            {document.clauses.map((clause) => (
              <li
                key={clause.clauseId}
                id={clause.anchorId}
                tabIndex={-1}
                data-clause-ref={clause.clauseRef}
                data-cited={clause.quotes > 0 || undefined}
                data-marked={clause.wholeMarked ? "clause" : clause.quotes > 0 ? "span" : undefined}
                className="scroll-mt-4 rounded-md border bg-surface-raised p-3 outline-none focus-visible:ring-2 focus-visible:ring-focus/50 data-[cited]:border-warning"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-semibold text-fg">
                    {t("workbench.source.clause", { ref: clause.clauseRef })}
                  </p>
                  <p className="text-xs text-fg-muted">
                    {clause.page === null
                      ? t("workbench.source.noPage")
                      : t("workbench.source.page", { page: clause.page })}
                  </p>
                </div>
                <p
                  className="mt-2 text-sm whitespace-pre-wrap text-fg"
                  data-slot="source-clause-text"
                >
                  <ClauseText clause={clause} />
                </p>
                {clause.unmatched.length === 0 ? null : (
                  <div className="mt-2 flex flex-col gap-1" data-slot="span-unmatched">
                    <p className="text-xs font-medium text-fg">{t("workbench.source.unmatched")}</p>
                    <ul className="ml-5 list-disc text-xs text-fg-muted">
                      {clause.unmatched.map((quote, index) => (
                        <li key={index}>{quote}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </article>
  );
}

export interface SourcePaneProps {
  pane: SourcePaneModel;
}

/**
 * The source pane: each document the draft rests on with its clauses (every cited quote marked,
 * or the whole clause when the quote does not match it word for word), a link to it in the
 * document viewer and to the file the pipeline stored, opened in a new tab and never framed here,
 * and the draft's citations with their verification.
 */
export function SourcePane({ pane }: SourcePaneProps) {
  return (
    <section
      aria-labelledby="pane-source"
      data-slot="source-pane"
      className="flex min-w-0 flex-col gap-4"
    >
      <h2 id="pane-source" className="text-lg font-semibold text-fg">
        {t("workbench.source.heading")}
      </h2>
      {pane.documents.length === 0 ? (
        <p className="text-sm text-fg-muted" data-slot="source-empty">
          {t("workbench.source.none")}
        </p>
      ) : (
        pane.documents.map((document) => (
          <DocumentSection key={document.documentId} document={document} />
        ))
      )}
      <div className="flex flex-col gap-2" data-slot="source-citations">
        <h3 className="text-base font-semibold text-fg">
          {t("workbench.source.citationsHeading")}
        </h3>
        {pane.citations.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("workbench.source.noCitations")}</p>
        ) : (
          <Table scrollLabel={t("workbench.source.citationsRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("workbench.source.citationsCaption", { count: pane.citations.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{t("workbench.source.column.clause")}</TableHead>
                <TableHead scope="col">{t("workbench.source.column.quote")}</TableHead>
                <TableHead scope="col">{t("workbench.source.column.verified")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pane.citations.map((citation) => (
                <TableRow key={citation.citationId} data-citation={citation.citationId}>
                  <TableCell className="align-top text-sm">
                    <Link
                      href={(citation.anchorHref ?? citation.viewerHref) as Route}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {citation.clauseRef}
                    </Link>
                  </TableCell>
                  <TableCell className="min-w-56 align-top text-sm">
                    <blockquote className="border-l-2 border-line-strong pl-3 whitespace-pre-wrap text-fg">
                      {citation.quote}
                    </blockquote>
                  </TableCell>
                  <TableCell className="align-top text-sm">
                    <div className="flex flex-col items-start gap-1">
                      {citation.verified ? (
                        <Badge tone="success">{t("workbench.source.verified")}</Badge>
                      ) : (
                        <Badge tone="warning">{t("workbench.source.notVerified")}</Badge>
                      )}
                      {citation.score === null ? null : (
                        <span>{t("workbench.source.score", { score: citation.score })}</span>
                      )}
                      {citation.verifiedAt === null ? null : (
                        <span className="text-xs text-fg-muted">{citation.verifiedAt}</span>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </section>
  );
}
