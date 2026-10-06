import type { Route } from "next";
import Link from "next/link";
import {
  Banner,
  KeyValue,
  PageHeader,
  StatusChip,
  Timeline,
  type KeyValueItem,
} from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { CitationList } from "@/shared/ui/citation-list";
import { NotLegalAdvice } from "@/shared/ui/not-legal-advice";
import { SectionNav } from "@/shared/ui/section-nav";
import type { ObligationPageView } from "../model/detail";
import { AssigneePanel, type AssigneeMode } from "./assignee-panel";
import { CommentForm } from "./comment-form";
import { StatusPanel } from "./status-panel";
import type { TrackingAction } from "./tracking-form";
import { WhyApplies } from "./why-applies";

export interface ObligationDetailViewProps {
  view: ObligationPageView;
  header: { crumbs: readonly Crumb[]; tabs: readonly NavLink[] };
  listHref: string;
  /** The signed-in user. */
  viewerId: string;
  actions: { status: TrackingAction; assign: TrackingAction; comment: TrackingAction };
  /** One Idempotency-Key per form, minted for this render. */
  keys: { status: string; assign: string; comment: string };
  assignee: { mode: AssigneeMode; text: string };
}

function facts(view: ObligationPageView, assigneeText: string): KeyValueItem[] {
  const items: KeyValueItem[] = [
    {
      key: "status",
      label: t("obligation.facts.status"),
      value: <StatusChip status={view.status} tone={view.statusTone} label={view.statusLabel} />,
    },
    {
      key: "due",
      label: t("obligation.facts.due"),
      value: (
        <span>
          {view.due}
          {view.dueNote === null ? null : (
            <span className={view.overdue ? "ml-2 font-medium text-danger" : "ml-2 text-fg-muted"}>
              {view.dueNote}
            </span>
          )}
        </span>
      ),
    },
    { key: "node", label: t("obligation.facts.node"), value: view.node },
    { key: "evidence", label: t("obligation.facts.evidence"), value: view.evidence },
    {
      key: "assignee",
      label: t("obligation.facts.assignee"),
      value: view.assigneeId === null ? t("obligation.assignee.nobodyShort") : assigneeText,
    },
  ];
  if (view.closed !== null) {
    items.splice(2, 0, { key: "closed", label: t("obligation.facts.closed"), value: view.closed });
  }
  return items;
}

/**
 * One obligation: what to do and by when (in India), for which GSTIN, the evidence it needs,
 * whether its rule has been reviewed and who approved its publication, the clauses it cites with
 * their text, why it applies, and its tracking: the status changes its status allows, who it is
 * given to, the comments and the history, oldest first.
 */
export function ObligationDetailView({
  view,
  header,
  listHref,
  viewerId,
  actions,
  keys,
  assignee,
}: ObligationDetailViewProps) {
  const { review } = view;
  return (
    <div data-slot="obligation-detail" className="flex max-w-4xl flex-col gap-8">
      <div className="flex flex-col gap-4">
        <PageHeader
          title={view.title}
          description={view.period ?? t("obligation.oneOff")}
          breadcrumbs={<Breadcrumbs crumbs={header.crumbs} />}
        />
        <SectionNav items={header.tabs} label={t("business.tabs")} />
      </div>
      <KeyValue items={facts(view, assignee.text)} aria-label={t("obligation.facts.label")} />

      <StatusPanel
        action={actions.status}
        businessId={view.businessId}
        obligationId={view.id}
        idempotencyKey={keys.status}
        actions={view.actions}
        title={view.title}
      />

      <section aria-labelledby="obligation-steps" className="flex flex-col gap-3">
        <h2 id="obligation-steps" className="text-lg font-semibold text-fg">
          {t("obligation.steps.heading")}
        </h2>
        {view.steps.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("obligation.steps.none")}</p>
        ) : (
          <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm text-fg">
            {view.steps.map((step, index) => (
              <li key={index}>{step}</li>
            ))}
          </ol>
        )}
      </section>

      <section
        aria-labelledby="obligation-rule"
        data-slot="obligation-rule"
        className="flex flex-col gap-3"
      >
        <h2 id="obligation-rule" className="text-lg font-semibold text-fg">
          {t("obligation.rule.heading")}
        </h2>
        {review.ruleTitle === null ? (
          <p className="text-sm text-fg-muted">{t("obligation.rule.unknown")}</p>
        ) : (
          <p className="text-sm text-fg">
            {review.ruleTitle}
            {review.effective === null ? null : (
              <span className="block text-xs text-fg-muted">{review.effective}</span>
            )}
          </p>
        )}
        {review.reviewed ? null : (
          <Banner
            tone="warning"
            title={t("obligation.rule.notReviewedTitle")}
            data-slot="not-reviewed"
          >
            {t("obligation.rule.notReviewedBody")}
          </Banner>
        )}
        <div data-slot="reviewed-by" className="flex flex-col gap-1 text-sm">
          {review.approvedBy.length === 0 ? (
            <p className="text-fg-muted">{t("obligation.rule.noApprovers")}</p>
          ) : (
            <>
              <p className="text-fg">
                {review.publishedAt === null
                  ? t("obligation.rule.approvedBy", { count: review.approvedBy.length })
                  : t("obligation.rule.approvedOn", {
                      count: review.approvedBy.length,
                      date: review.publishedAt,
                    })}
              </p>
              <ul className="ml-5 list-disc">
                {review.approvedBy.map((approver) => (
                  <li key={approver} data-approver={approver}>
                    <code className="font-mono text-xs">{approver}</code>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </section>

      <section aria-labelledby="obligation-citations" className="flex flex-col gap-3">
        <h2 id="obligation-citations" className="text-lg font-semibold text-fg">
          {t("obligation.citations.heading")}
        </h2>
        <CitationList citations={view.citations} empty={t("obligation.citations.none")} />
      </section>

      <WhyApplies why={view.why} node={view.node} />

      <AssigneePanel
        action={actions.assign}
        businessId={view.businessId}
        obligationId={view.id}
        idempotencyKey={keys.assign}
        assigneeId={view.assigneeId}
        assigneeText={assignee.text}
        viewerId={viewerId}
        mode={assignee.mode}
        open={view.open}
      />

      <section aria-labelledby="obligation-comments" className="flex flex-col gap-3">
        <h2 id="obligation-comments" className="text-lg font-semibold text-fg">
          {t("obligation.comments.heading")}
        </h2>
        {view.comments.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("obligation.comments.none")}</p>
        ) : (
          <ul className="flex flex-col gap-3" data-slot="comments">
            {view.comments.map((comment) => (
              <li
                key={comment.id}
                data-comment={comment.id}
                className="rounded-md border border-line p-3"
              >
                <p className="text-xs text-fg-muted">
                  {comment.author} · <time dateTime={comment.dateTime}>{comment.when}</time>
                </p>
                <p className="mt-1 text-sm whitespace-pre-wrap text-fg">{comment.body}</p>
              </li>
            ))}
          </ul>
        )}
        <CommentForm
          action={actions.comment}
          businessId={view.businessId}
          obligationId={view.id}
          idempotencyKey={keys.comment}
        />
      </section>

      <section aria-labelledby="obligation-history" className="flex flex-col gap-3">
        <h2 id="obligation-history" className="text-lg font-semibold text-fg">
          {t("obligation.history.heading")}
        </h2>
        {view.history.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("obligation.history.none")}</p>
        ) : (
          <Timeline
            data-slot="history"
            events={view.history.map((item) => ({
              id: item.id,
              label: item.when,
              dateTime: item.dateTime,
              title: item.title,
              body: item.body ?? undefined,
              tone: item.tone,
            }))}
          />
        )}
      </section>

      <p className="text-sm">
        <Link href={listHref as Route} className="text-primary underline-offset-2 hover:underline">
          {t("obligation.backToList")}
        </Link>
      </p>
      <NotLegalAdvice />
    </div>
  );
}
