import type { Route } from "next";
import Link from "next/link";
import { Button, KeyValue, PageHeader, type KeyValueItem } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  OBLIGATION_STATUS_FIELDS,
  closureReasonLabel,
  dueDateText,
  duePhrase,
  evidenceTypeText,
  isObligationOverdue,
  obligationStatusLabel,
  obligationStatusTone,
  periodText,
  statusChangeLabel,
  statusChanges,
  type ClosureReason,
  type Obligation,
  type ObligationStatusChange,
} from "../model/obligations";

export interface ObligationDetailViewProps {
  obligation: Obligation;
  /** The obligation's evidence page; without it the page shows no evidence link. */
  evidenceHref?: Route;
  /**
   * Moves the obligation to the status read from OBLIGATION_STATUS_FIELDS.status (a server
   * action). No route changes a status yet, so the buttons show only when the page passes one.
   */
  statusAction?: (formData: FormData) => Promise<void>;
  /** Now, for the due date; tests pass a fixed instant. */
  now?: Date;
}

/** "Completed on 10 Oct 2026"; the date alone when the service names no reason. */
function closedText(closedAt: string, reason: ClosureReason | null): string {
  const date = formatDate(closedAt);
  return reason === null
    ? date
    : t("obligations.detail.closedValue", { date, reason: closureReasonLabel(reason) });
}

/** When it was closed (once it is), then the rule version and decision it came from. */
function facts(item: Obligation): KeyValueItem[] {
  const origin: KeyValueItem[] = [
    {
      key: "rule-version",
      label: t("obligations.detail.ruleVersion"),
      value: <code className="font-mono text-xs">{item.ruleVersionId}</code>,
      copy: item.ruleVersionId,
    },
    {
      key: "decision",
      label: t("obligations.detail.decision"),
      value: <code className="font-mono text-xs">{item.decisionId}</code>,
      copy: item.decisionId,
    },
  ];
  if (item.closedAt === null) return origin;
  const closed = closedText(item.closedAt, item.closedReason);
  return [{ key: "closed", label: t("obligations.detail.closed"), value: closed }, ...origin];
}

function StatusForms({
  action,
  changes,
}: {
  action: (formData: FormData) => Promise<void>;
  changes: readonly ObligationStatusChange[];
}) {
  return (
    <section aria-labelledby="obligation-status" className="flex flex-col gap-3">
      <h2 id="obligation-status" className="text-lg font-semibold text-fg">
        {t("obligations.detail.updateTitle")}
      </h2>
      <div className="flex flex-wrap gap-2">
        {changes.map((change) => (
          <form key={change} action={action} data-change={change}>
            <input type="hidden" name={OBLIGATION_STATUS_FIELDS.status} value={change} />
            <Button type="submit" variant={change === "done" ? "primary" : "secondary"}>
              {statusChangeLabel(change)}
            </Button>
          </form>
        ))}
      </div>
    </section>
  );
}

/**
 * One obligation: its status, due date and the evidence it needs, the steps to meet it and the
 * rule version and decision behind it. The evidence link and the status buttons show only when
 * the page passes them.
 */
export function ObligationDetailView({
  obligation,
  evidenceHref,
  statusAction,
  now = new Date(),
}: ObligationDetailViewProps) {
  const overdue = isObligationOverdue(obligation, now);
  const changes = statusChanges(obligation.status);
  return (
    <div data-slot="obligation-detail" className="flex flex-col gap-6">
      <PageHeader
        title={obligation.title}
        description={periodText(obligation) ?? t("obligations.detail.oneOff")}
        actions={
          evidenceHref === undefined ? undefined : (
            <Button asChild variant="secondary">
              <Link href={evidenceHref}>{t("obligations.detail.evidenceLink")}</Link>
            </Button>
          )
        }
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label={t("obligations.detail.status")}
          value={obligationStatusLabel(obligation.status)}
          tone={obligationStatusTone(obligation.status)}
        />
        <StatCard
          label={t("obligations.detail.due")}
          value={dueDateText(obligation)}
          tone={overdue ? "danger" : "neutral"}
          hint={duePhrase(obligation, now)}
        />
        <StatCard
          label={t("obligations.detail.evidence")}
          value={evidenceTypeText(obligation.evidenceType)}
        />
      </div>
      {statusAction === undefined || changes.length === 0 ? null : (
        <StatusForms action={statusAction} changes={changes} />
      )}
      <section aria-labelledby="obligation-steps" className="flex flex-col gap-3">
        <h2 id="obligation-steps" className="text-lg font-semibold text-fg">
          {t("obligations.detail.stepsTitle")}
        </h2>
        {obligation.steps.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("obligations.detail.noSteps")}</p>
        ) : (
          <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm text-fg">
            {obligation.steps.map((step, index) => (
              <li key={index}>{step}</li>
            ))}
          </ol>
        )}
      </section>
      <section aria-labelledby="obligation-facts" className="flex flex-col gap-3">
        <h2 id="obligation-facts" className="text-lg font-semibold text-fg">
          {t("obligations.detail.factsTitle")}
        </h2>
        <KeyValue items={facts(obligation)} />
      </section>
    </div>
  );
}
