import type { Route } from "next";
import Link from "next/link";
import {
  KeyValue,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  type KeyValueItem,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ApplicabilityBadge } from "@/shared/ui/applicability";
import type { ReviewItemView } from "../model/items";
import { ResolvePanel, type ResolveAction } from "./resolve-panel";

export interface ReviewItemCardProps {
  item: ReviewItemView;
  /** Bound to the tenant and this item; null when the session may only read. */
  resolveAction: ResolveAction | null;
}

/**
 * One review item: the version and the node it is about, why it needs a person, the decision
 * under review with each condition's outcome in the engine's words, and either how it was
 * settled or, for a reviewer or an admin, the way to settle it.
 */
export function ReviewItemCard({ item, resolveAction }: ReviewItemCardProps) {
  const headingId = `review-item-${item.id}`;
  const facts: KeyValueItem[] = [
    {
      key: "business",
      label: t("decisions.facts.business"),
      value: <code className="font-mono text-xs">{item.businessId}</code>,
      copy: item.businessId,
    },
    { key: "reason", label: t("decisions.facts.reason"), value: item.reason },
    {
      key: "opened",
      label: t("decisions.facts.opened"),
      value: <time dateTime={item.openedIso}>{item.opened}</time>,
    },
    {
      key: "decision",
      label: t("decisions.facts.decision"),
      value: (
        <span className="flex flex-wrap items-center gap-2">
          <ApplicabilityBadge
            result={item.decision.result}
            needsReview={item.decision.needsReview}
          />
          <span className="text-fg-muted">
            {t("decisions.facts.decisionSummary", {
              confidence: item.decision.confidence,
              decided: item.decision.decided,
              trigger: item.decision.trigger,
              profile: item.decision.profileVersion,
            })}
          </span>
        </span>
      ),
    },
    ...(item.decision.year === null
      ? []
      : [{ key: "year", label: t("decisions.facts.year"), value: item.decision.year }]),
  ];
  return (
    <article
      aria-labelledby={headingId}
      data-review-item={item.id}
      data-status={item.status}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip status={item.status} tone={item.statusTone} label={item.statusLabel} />
        </div>
        <h3 id={headingId} className="text-base font-semibold text-fg">
          <Link
            href={item.versionHref as Route}
            className="text-primary underline-offset-2 hover:underline"
          >
            {item.versionName}
          </Link>
        </h3>
        {item.versionTitle === null ? null : (
          <p className="text-sm text-fg-muted">{item.versionTitle}</p>
        )}
      </div>
      <KeyValue items={facts} aria-label={t("decisions.facts.label")} />
      {item.predicates.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("decisions.noConditions")}</p>
      ) : (
        <Table scrollLabel={t("decisions.conditionsRegion")}>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("decisions.conditionsCaption")}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("decisions.column.condition")}</TableHead>
              <TableHead scope="col">{t("decisions.column.outcome")}</TableHead>
              <TableHead scope="col">{t("decisions.column.reason")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {item.predicates.map((predicate, index) => (
              <TableRow
                key={`${predicate.attribute}-${index}`}
                data-attribute={predicate.attribute}
              >
                <TableCell className="align-top whitespace-normal">
                  <span className="block">{predicate.description}</span>
                  <span className="block text-xs text-fg-muted">
                    <code className="font-mono">{predicate.attribute}</code> · {predicate.kind}
                  </span>
                </TableCell>
                <TableCell className="align-top">
                  <ApplicabilityBadge
                    result={predicate.outcome}
                    needsReview={predicate.needsReview}
                  />
                  <span className="mt-1 block text-xs text-fg-muted">
                    {t("decisions.confidence", { confidence: predicate.confidence })}
                  </span>
                </TableCell>
                <TableCell className="align-top whitespace-normal text-fg-muted">
                  {predicate.reason}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {item.resolution !== null ? (
        <div className="flex flex-col gap-1 text-sm" data-slot="resolution">
          <p className="font-medium text-fg">
            {item.resolution.at === null
              ? t("decisions.settled", { label: item.resolution.label, by: item.resolution.by })
              : t("decisions.settledAt", {
                  label: item.resolution.label,
                  by: item.resolution.by,
                  at: item.resolution.at,
                })}
          </p>
          {item.resolution.note === "" ? null : (
            <p className="text-fg-muted">{t("decisions.note", { note: item.resolution.note })}</p>
          )}
          {item.resolution.decisionId === null ? null : (
            <p className="text-xs text-fg-muted">
              {t("decisions.appended")}{" "}
              <code className="font-mono">{item.resolution.decisionId}</code>
            </p>
          )}
        </div>
      ) : resolveAction === null ? (
        <p className="text-sm text-fg-muted" data-slot="resolve-reviewer-only">
          {t("decisions.resolve.reviewerOnly")}
        </p>
      ) : (
        <ResolvePanel action={resolveAction} versionName={item.versionName} />
      )}
    </article>
  );
}
