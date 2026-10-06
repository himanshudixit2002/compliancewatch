import type { Route } from "next";
import Link from "next/link";
import { Badge, Banner, ErrorState, StatusChip } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { CitationList } from "@/shared/ui/citation-list";
import type { ChangeCardView } from "../model/changes";

export interface ChangeCardProps {
  card: ChangeCardView;
}

/**
 * One change as a card: what happened to which rule version and when, its dates, whether it
 * applies to this business (from the change's impact, node by node), the not-yet-reviewed warning
 * while no analyst has reviewed it, who approved its publication, and what it cites.
 */
export function ChangeCard({ card }: ChangeCardProps) {
  const headingId = `change-${card.id}`;
  return (
    <article
      aria-labelledby={headingId}
      data-change={card.id}
      data-rule-version={card.ruleVersionId}
      data-applicability={card.applicability.value}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={card.kind} tone={card.kindTone} label={card.kindLabel} />
        <Badge tone={card.applicability.tone} data-slot="applicability">
          {card.applicability.label}
        </Badge>
      </div>
      <h2 id={headingId} className="text-lg font-semibold text-fg">
        {card.title}
      </h2>
      <p className="text-xs text-fg-muted">
        {t("changes.meta", { version: card.version, regulator: card.regulator })}{" "}
        <time dateTime={card.changedAtIso}>{t("changes.changedAt", { when: card.changedAt })}</time>
      </p>
      {card.summary === "" ? null : <p className="max-w-prose text-sm text-fg">{card.summary}</p>}
      <ul className="flex flex-col gap-1 text-sm text-fg-muted">
        <li>{card.effective}</li>
        {card.deadline === null ? null : <li>{card.deadline}</li>}
        {card.relations.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {card.applicability.details.length === 0 ? null : (
        <ul className="flex flex-col gap-1 text-sm text-fg" data-slot="applicability-details">
          {card.applicability.details.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {card.impactHref === null ? null : (
        <p className="text-sm">
          <Link
            href={card.impactHref as Route}
            className="text-primary underline-offset-2 hover:underline"
            data-slot="impact-link"
          >
            {t("changes.allClients")}
          </Link>
        </p>
      )}
      {card.applicability.failure === null ? null : (
        <ErrorState
          title={t("changes.impactFailed")}
          detail={card.applicability.failure.message}
          correlationId={card.applicability.failure.correlationId ?? undefined}
        />
      )}
      {card.needsReview ? (
        <Banner tone="warning" title={t("changes.notReviewedTitle")} data-slot="not-reviewed">
          {t("changes.notReviewedBody")}
        </Banner>
      ) : null}
      <div className="text-sm" data-slot="reviewed-by">
        {card.approvedBy.length === 0 ? (
          <p className="text-fg-muted">{t("changes.noApprovers")}</p>
        ) : (
          <>
            <p className="text-fg">
              {card.publishedAt === null
                ? t("changes.approvedBy", { count: card.approvedBy.length })
                : t("changes.approvedOn", {
                    count: card.approvedBy.length,
                    date: card.publishedAt,
                  })}
            </p>
            <ul className="ml-5 list-disc">
              {card.approvedBy.map((approver) => (
                <li key={approver} data-approver={approver}>
                  <code className="font-mono text-xs">{approver}</code>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-primary">
          {card.citations.length === 1
            ? t("changes.citationsOne")
            : t("changes.citationsMany", { count: card.citations.length })}
        </summary>
        <div className="mt-2">
          <CitationList citations={card.citations} empty={t("changes.noCitations")} />
        </div>
      </details>
    </article>
  );
}
