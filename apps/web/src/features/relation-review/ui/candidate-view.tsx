import type { Route } from "next";
import Link from "next/link";
import { Banner, HighlightMark, KeyValue, PageHeader, StatusChip } from "@compliancewatch/ui";
import type { KeyValueItem } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError } from "@/shared/ui/service-error";
import type { CandidatePage } from "../queries";
import { CandidateDecisions, type CandidateAction } from "./candidate-decisions";

export interface CandidateViewProps {
  title: string;
  crumbs: readonly Crumb[];
  page: CandidatePage;
  /** The two decisions, bound to the candidate; offered only when access allows them. */
  approve: CandidateAction | null;
  reject: CandidateAction | null;
}

const TONES = { open: "warning", approved: "success", rejected: "neutral" } as const;

function factItems(page: CandidatePage): KeyValueItem[] {
  const { facts } = page;
  const items: KeyValueItem[] = [
    {
      key: "status",
      label: t("relationReview.fact.status"),
      value: (
        <StatusChip
          status={facts.status}
          tone={TONES[facts.status as keyof typeof TONES] ?? "neutral"}
          label={facts.statusLabel}
        />
      ),
    },
    { key: "relation", label: t("relationReview.fact.relation"), value: facts.relationLabel },
    {
      key: "target",
      label: t("relationReview.fact.target"),
      value: (
        <span>
          {facts.targetTypeLabel}: <span className="font-mono">{facts.targetName}</span>
        </span>
      ),
    },
    {
      key: "alignment",
      label: t("relationReview.fact.alignment"),
      value:
        facts.targetEntityHref === null ? (
          facts.targetGroupHref === null ? (
            t("relationReview.unaligned")
          ) : (
            <span>
              {t("relationReview.unaligned")}{" "}
              <Link
                href={facts.targetGroupHref as Route}
                className="text-primary underline underline-offset-2"
              >
                {t("relationReview.alignInReview")}
              </Link>
            </span>
          )
        ) : (
          <Link
            href={facts.targetEntityHref as Route}
            className="text-primary underline-offset-2 hover:underline"
          >
            {t("relationReview.alignedTo", { id: facts.targetEntityId ?? "" })}
          </Link>
        ),
    },
  ];
  if (facts.targetRuleKey !== null) {
    items.push({
      key: "rule",
      label: t("relationReview.fact.ruleKey"),
      value: facts.targetRuleKey,
    });
  }
  if (facts.period !== null) {
    items.push({ key: "period", label: t("relationReview.fact.period"), value: facts.period });
  }
  items.push(
    { key: "quote", label: t("relationReview.fact.quoteScore"), value: facts.quoteScore },
    { key: "confidence", label: t("relationReview.fact.confidence"), value: facts.confidence },
    {
      key: "proposed",
      label: t("relationReview.fact.proposedBy"),
      value: t("relationReview.proposedBy", { model: facts.model, prompt: facts.promptVersion }),
    },
  );
  if (facts.decidedBy !== "") {
    items.push({
      key: "decided",
      label: t("relationReview.fact.decidedBy"),
      value: facts.decidedBy,
    });
  }
  if (facts.rejectReasonLabel !== null) {
    items.push({
      key: "reason",
      label: t("relationReview.fact.rejectReason"),
      value: facts.rejectReasonLabel,
    });
  }
  items.push({
    key: "id",
    label: t("relationReview.fact.id"),
    value: <code className="font-mono text-xs">{facts.candidateId}</code>,
    copy: facts.candidateId,
    copyLabel: t("relationReview.copyId"),
  });
  return items;
}

/**
 * One relation candidate: what it proposes, how sure the pipeline was and what it flagged, the
 * evidence clause with the quote marked, and the decision. The decision is offered when the
 * session may send it (the role, web.admin_rulebook_writes and the review token); otherwise the
 * page names what holds it back. A decided candidate shows who decided it and how.
 */
export function CandidateView({ title, crumbs, page, approve, reject }: CandidateViewProps) {
  const { facts, evidence } = page;
  const name = t("relationReview.name", {
    relation: facts.relationLabel,
    type: facts.targetTypeLabel,
    target: facts.targetName,
  });
  return (
    <div data-slot="relation-candidate" className="flex max-w-5xl flex-col gap-6">
      <PageHeader title={title} description={name} breadcrumbs={<Breadcrumbs crumbs={crumbs} />} />
      {facts.needsReview || facts.issues.length > 0 ? (
        <Banner
          tone="warning"
          title={t("relationReview.flaggedTitle")}
          data-slot="candidate-issues"
        >
          {facts.issues.length === 0 ? (
            t("relationReview.flaggedBody")
          ) : (
            <ul className="list-disc pl-5">
              {facts.issues.map((issue) => (
                <li key={issue.code}>
                  {issue.label}
                  {issue.detail === "" ? null : `: ${issue.detail}`}
                </li>
              ))}
            </ul>
          )}
        </Banner>
      ) : null}
      <KeyValue items={factItems(page)} data-slot="candidate-facts" />
      <section aria-labelledby="candidate-evidence" className="flex flex-col gap-3">
        <h2 id="candidate-evidence" className="text-lg font-semibold text-fg">
          {t("relationReview.evidence")}
        </h2>
        {evidence.mark === null ? (
          <blockquote className="max-w-prose border-l-2 border-line-strong pl-3 text-sm whitespace-pre-wrap text-fg">
            {evidence.quote}
          </blockquote>
        ) : (
          <p
            className="max-w-prose text-sm whitespace-pre-wrap text-fg"
            data-slot="evidence-clause"
          >
            {evidence.mark.before}
            <HighlightMark
              startLabel={t("relationReview.markStart")}
              endLabel={t("relationReview.markEnd")}
            >
              {evidence.mark.mark}
            </HighlightMark>
            {evidence.mark.after}
          </p>
        )}
        <p className="text-sm text-fg-muted">
          {evidence.clauseRef === null
            ? null
            : t("relationReview.evidenceSource", {
                clause: evidence.clauseRef,
                document: evidence.documentTitle ?? "",
              })}{" "}
          <Link href={evidence.href as Route} className="text-primary underline underline-offset-2">
            {t("relationReview.showInDocument")}
          </Link>
        </p>
        {page.evidenceError === null ? null : <ServiceError error={page.evidenceError} />}
        {page.evidenceError === null && evidence.mark === null ? (
          <p className="text-sm text-fg-muted">{t("relationReview.quoteNotFound")}</p>
        ) : null}
      </section>
      {page.access.allowed && approve !== null && reject !== null ? (
        <CandidateDecisions
          approve={approve}
          reject={reject}
          open={facts.open}
          statusLabel={facts.statusLabel}
          name={name}
          needsTarget={page.needsTarget}
          aligned={facts.targetEntityId !== null}
          options={page.options}
          optionsError={
            page.optionsError === null
              ? null
              : {
                  title: page.optionsError.message,
                  ...(page.optionsError.problem?.detail
                    ? { detail: page.optionsError.problem.detail }
                    : {}),
                  ...(page.optionsError.requestId === ""
                    ? {}
                    : { correlationId: page.optionsError.requestId }),
                }
          }
        />
      ) : facts.open ? (
        page.access.allowed ? null : (
          <Banner tone="warning" title={page.access.title} data-slot="decision-refused">
            {page.access.detail ?? null}
          </Banner>
        )
      ) : (
        <p className="text-sm text-fg-muted" data-slot="candidate-closed">
          {t("relationReview.closedNote", { status: facts.statusLabel })}
        </p>
      )}
    </div>
  );
}
