import {
  Banner,
  ErrorState,
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
import type { WhyView } from "../model/detail";

export interface WhyAppliesProps {
  why: WhyView;
  /** The node the decision is about, named by its GSTIN or PAN. */
  node: string;
}

/**
 * Why the obligation applies: the applicability engine's latest decision of its rule for its
 * node, with every condition of the rule in the engine's words, how it came out on the profile
 * and why. An unsure condition is never guessed; a decision that needs review says so.
 */
export function WhyApplies({ why, node }: WhyAppliesProps) {
  return (
    <section
      aria-labelledby="obligation-why"
      data-slot="why-applies"
      className="flex flex-col gap-3"
    >
      <h2 id="obligation-why" className="text-lg font-semibold text-fg">
        {t("obligation.why.heading")}
      </h2>
      {why.state === "error" ? (
        <ErrorState
          title={t("obligation.why.failed")}
          detail={why.message}
          correlationId={why.correlationId ?? undefined}
        />
      ) : why.state === "none" ? (
        <p className="text-sm text-fg-muted">{t("obligation.why.none", { node })}</p>
      ) : (
        <>
          <p className="flex flex-wrap items-center gap-2 text-sm text-fg">
            <StatusChip status={why.result} tone={why.tone} label={why.result} />
            <span>
              {t("obligation.why.summary", {
                node,
                confidence: why.confidence,
                decided: why.decidedAt,
              })}
            </span>
          </p>
          {why.year === null ? null : (
            <p className="text-xs text-fg-muted">{t("obligation.why.year", { year: why.year })}</p>
          )}
          {why.later ? <p className="text-xs text-fg-muted">{t("obligation.why.later")}</p> : null}
          {why.needsReview ? (
            <Banner tone="warning" title={t("obligation.why.needsReview")} />
          ) : null}
          {why.predicates.length === 0 ? (
            <p className="text-sm text-fg-muted">{t("obligation.why.noConditions")}</p>
          ) : (
            <Table scrollLabel={t("obligation.why.tableRegion")}>
              <TableCaption className="text-left text-sm text-fg-muted">
                {t("obligation.why.caption")}
              </TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">{t("obligation.why.condition")}</TableHead>
                  <TableHead scope="col">{t("obligation.why.outcome")}</TableHead>
                  <TableHead scope="col">{t("obligation.why.reason")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {why.predicates.map((predicate, index) => (
                  <TableRow
                    key={`${predicate.attribute}-${index}`}
                    data-attribute={predicate.attribute}
                  >
                    <TableCell className="align-top whitespace-normal">
                      {predicate.description}
                    </TableCell>
                    <TableCell className="align-top">
                      <StatusChip
                        status={predicate.outcome}
                        tone={predicate.tone}
                        label={predicate.outcome}
                      />
                      <span className="mt-1 block text-xs text-fg-muted">
                        {t("obligation.why.confidence", { confidence: predicate.confidence })}
                      </span>
                    </TableCell>
                    <TableCell className="align-top whitespace-normal text-fg-muted">
                      {predicate.reason}
                      {predicate.needsReview ? (
                        <span className="block text-xs font-medium text-fg">
                          {t("obligation.why.predicateReview")}
                        </span>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </>
      )}
    </section>
  );
}
