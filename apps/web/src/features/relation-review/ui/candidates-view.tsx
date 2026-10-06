import type { Route } from "next";
import Link from "next/link";
import {
  Button,
  EmptyState,
  Field,
  Input,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { CandidateStatus } from "@/entities/rulebook/types";
import type { Crumb } from "@/shared/config/nav";
import { t, type MessageKey } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { FilterChips } from "@/shared/ui/filter-chips";
import { KeysetPager } from "@/shared/ui/keyset-pager";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import {
  CANDIDATE_PARAMS,
  candidateQueueHref,
  candidateStatusLabel,
  statusChips,
  type CandidateFilter,
  type CandidateQueueRead,
  type CandidateQueueView,
} from "../model/queue";

export interface CandidatesViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The queue itself, without a query: the chips' and the form's base. */
  pageHref: string;
  read: CandidateQueueRead;
  /** The page the filter found; null when the filter was refused or the read failed. */
  view: CandidateQueueView | null;
  error?: ServiceErrorLike;
}

interface EmptyWords {
  /** Nothing in the status anywhere. */
  title: MessageKey;
  body: MessageKey;
  /** Nothing in the status for the document the form names. */
  documentTitle: MessageKey;
  /** Nothing after the previous page's last candidate. */
  laterTitle: MessageKey;
}

const EMPTY: Readonly<Record<CandidateStatus, EmptyWords>> = {
  open: {
    title: "relationReview.empty.openTitle",
    body: "relationReview.empty.openBody",
    documentTitle: "relationReview.empty.openDocumentTitle",
    laterTitle: "relationReview.empty.openLaterTitle",
  },
  approved: {
    title: "relationReview.empty.approvedTitle",
    body: "relationReview.empty.approvedBody",
    documentTitle: "relationReview.empty.approvedDocumentTitle",
    laterTitle: "relationReview.empty.approvedLaterTitle",
  },
  rejected: {
    title: "relationReview.empty.rejectedTitle",
    body: "relationReview.empty.rejectedBody",
    documentTitle: "relationReview.empty.rejectedDocumentTitle",
    laterTitle: "relationReview.empty.rejectedLaterTitle",
  },
};

/**
 * Why a page holds no candidate: a later page past the list's end (the first page is offered
 * below), the document the form names, or the status itself.
 */
function emptyText(filter: CandidateFilter): { title: string; body: string } {
  const words = EMPTY[filter.status];
  if (filter.after !== null) {
    return { title: t(words.laterTitle), body: t("relationReview.empty.laterBody") };
  }
  if (filter.documentId !== null) {
    return { title: t(words.documentTitle), body: t("relationReview.empty.documentBody") };
  }
  return { title: t(words.title), body: t(words.body) };
}

const TONES = { open: "warning", approved: "success", rejected: "neutral" } as const;

/**
 * The relation candidates: what the pipeline proposed each document says about a rule or an
 * entity, by status (open by default), one document's or every document's, each with its
 * evidence quote linked into the document, the match and confidence scores, the issues the
 * pipeline raised and, for a deadline, the period and the new due date. A candidate opens on its
 * own page, where an analyst approves or rejects it.
 */
export function CandidatesView({
  title,
  crumbs,
  pageHref,
  read,
  view,
  error,
}: CandidatesViewProps) {
  const filter = read.filter;
  const empty = emptyText(filter);
  return (
    <div data-slot="relation-candidates" className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("relationReview.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <FilterChips label={t("relationReview.chipsLabel")} chips={statusChips(pageHref, filter)} />
      <form
        method="get"
        action={pageHref}
        aria-label={t("relationReview.filterLabel")}
        data-slot="candidate-filter"
        noValidate
        className="flex flex-wrap items-end gap-3"
      >
        {filter.status === "open" ? null : (
          <input type="hidden" name={CANDIDATE_PARAMS.status} value={filter.status} />
        )}
        <Field
          id="candidates-document"
          label={t("relationReview.documentField")}
          description={t("relationReview.documentHelp")}
          error={read.kind === "invalid" ? t("relationReview.documentInvalid") : undefined}
          className="w-full max-w-md"
        >
          <Input
            name={CANDIDATE_PARAMS.document}
            defaultValue={read.kind === "invalid" ? read.value : (filter.documentId ?? "")}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("relationReview.filterSubmit")}
        </Button>
        {filter.documentId === null ? null : (
          <Link
            href={
              candidateQueueHref(pageHref, { ...filter, documentId: null, after: null }) as Route
            }
            className="pb-2 text-sm text-primary underline-offset-2 hover:underline"
          >
            {t("relationReview.everyDocument")}
          </Link>
        )}
      </form>
      {error !== undefined ? <ServiceError error={error} /> : null}
      {view === null ? null : view.rows.length === 0 ? (
        <>
          <EmptyState title={empty.title} body={empty.body} />
          <KeysetPager
            nextHref={null}
            firstHref={view.firstHref}
            label={t("relationReview.pager")}
            nextLabel={t("relationReview.nextPage")}
            firstLabel={t("relationReview.firstPage")}
          />
        </>
      ) : (
        <>
          <Table scrollLabel={t("relationReview.tableRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("relationReview.caption", {
                count: view.rows.length,
                status: candidateStatusLabel(filter.status),
              })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("relationReview.column.relation")}</TableHead>
                <TableHead>{t("relationReview.column.target")}</TableHead>
                <TableHead>{t("relationReview.column.evidence")}</TableHead>
                <TableHead>{t("relationReview.column.scores")}</TableHead>
                <TableHead>{t("relationReview.column.status")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.rows.map((row) => (
                <TableRow
                  key={row.candidateId}
                  data-candidate={row.candidateId}
                  data-status={row.status}
                >
                  <TableCell className="align-top">
                    <div className="flex flex-col gap-1">
                      <Link
                        href={row.href as Route}
                        className="font-medium text-primary underline-offset-2 hover:underline"
                      >
                        {row.relationLabel}
                      </Link>
                      {row.period === null ? null : (
                        <span className="text-xs text-fg-muted">{row.period}</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="align-top text-sm">
                    <div className="flex flex-col gap-1">
                      <span>
                        {row.targetLabel}: <span className="font-mono">{row.targetName}</span>
                      </span>
                      <span className="text-xs text-fg-muted">
                        {row.aligned ? t("relationReview.aligned") : t("relationReview.unaligned")}
                      </span>
                      {row.targetRuleKey === null ? null : (
                        <span className="text-xs text-fg-muted">
                          {t("relationReview.ruleKey", { rule: row.targetRuleKey })}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="min-w-72 align-top text-sm">
                    <div className="flex flex-col gap-1">
                      <blockquote className="border-l-2 border-line-strong pl-3 whitespace-pre-wrap text-fg">
                        {row.evidenceQuote}
                      </blockquote>
                      <Link
                        href={row.evidenceHref as Route}
                        className="text-xs text-primary underline-offset-2 hover:underline"
                      >
                        {t("relationReview.showInDocument")}
                      </Link>
                    </div>
                  </TableCell>
                  <TableCell className="align-top text-sm">
                    <div className="flex flex-col gap-1">
                      <span>{t("relationReview.quoteScore", { score: row.quoteScore })}</span>
                      <span>{t("relationReview.confidence", { score: row.confidence })}</span>
                      {row.needsReview ? (
                        <span className="text-xs font-medium text-fg">
                          {t("relationReview.needsReview")}
                        </span>
                      ) : null}
                      {row.issues.length === 0 ? null : (
                        <span className="text-xs text-fg-muted">
                          {t("relationReview.issues", { issues: row.issues.join(", ") })}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <StatusChip
                      status={row.status}
                      tone={TONES[row.status as keyof typeof TONES] ?? "neutral"}
                      label={row.statusLabel}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <KeysetPager
            nextHref={view.nextHref}
            firstHref={view.firstHref}
            label={t("relationReview.pager")}
            nextLabel={t("relationReview.nextPage")}
            firstLabel={t("relationReview.firstPage")}
          />
        </>
      )}
    </div>
  );
}
