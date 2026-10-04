import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Button,
  DateField,
  EmptyState,
  HighlightMark,
  KeyValue,
  PageHeader,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { RuleVersionStatusChip } from "@/shared/ui/rule-version-status";
import { ServiceError } from "@/shared/ui/service-error";
import type { EntityPageView, MentionedClauseView } from "../model/entity-page";

export interface EntityViewProps {
  view: EntityPageView;
  crumbs: readonly Crumb[];
  /** The page itself, without a query: the as-of form's action. */
  pageHref: string;
  /** A malformed as-of date, as typed; nothing is filtered while it is set. */
  invalidAsOf?: string;
}

function ClauseText({ clause }: { clause: MentionedClauseView }) {
  return (
    <p className="text-sm whitespace-pre-wrap text-fg">
      {clause.segments.map((segment, index) =>
        segment.mark ? (
          <HighlightMark
            key={index}
            startLabel={t("entities.markStart")}
            endLabel={t("entities.markEnd")}
          >
            {segment.text}
          </HighlightMark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </p>
  );
}

/**
 * One canonical entity: its type, canonical name and aliases, the clauses that mention it with
 * the mentions marked (newest document first; with a date, only documents published by then,
 * and whether each clause's rule is out of force on it), and the relations from rule versions
 * that point at it.
 */
export function EntityView({ view, crumbs, pageHref, invalidAsOf }: EntityViewProps) {
  const { entity } = view;
  return (
    <div data-slot="canonical-entity" className="flex max-w-5xl flex-col gap-8">
      <PageHeader
        title={entity.canonicalName}
        description={t("entities.page.intro", { type: view.typeLabel })}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <KeyValue
        data-slot="entity-facts"
        items={[
          { key: "type", label: t("entities.fact.type"), value: view.typeLabel },
          {
            key: "name",
            label: t("entities.fact.name"),
            value: <code className="font-mono text-sm">{entity.canonicalName}</code>,
          },
          {
            key: "aliases",
            label: t("entities.fact.aliases"),
            value:
              entity.aliases.length === 0 ? (
                t("entities.noAliases")
              ) : (
                <ul className="flex flex-wrap gap-1" data-slot="aliases">
                  {entity.aliases.map((alias) => (
                    <li key={alias}>
                      <Badge>{alias}</Badge>
                    </li>
                  ))}
                </ul>
              ),
          },
          {
            key: "id",
            label: t("entities.fact.id"),
            value: <code className="font-mono text-xs">{entity.entityId}</code>,
            copy: entity.entityId,
          },
        ]}
      />
      <section aria-labelledby="entity-clauses" className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 id="entity-clauses" className="text-lg font-semibold text-fg">
            {t("entities.page.clausesHeading")}
          </h2>
          <p className="max-w-prose text-sm text-fg-muted">{t("entities.page.clausesIntro")}</p>
        </div>
        <form
          method="get"
          action={pageHref}
          aria-label={t("entities.page.asOfForm")}
          noValidate
          className="flex flex-wrap items-end gap-3"
        >
          <DateField
            id="entity-as-of"
            name="as_of"
            label={t("entities.page.asOf")}
            description={t("entities.page.asOfHelp")}
            defaultValue={invalidAsOf ?? view.asOf ?? ""}
            error={invalidAsOf === undefined ? undefined : t("ruleVersions.asOfInvalid")}
          />
          <Button type="submit" variant="secondary">
            {t("entities.page.apply")}
          </Button>
        </form>
        {!view.clauses.ok ? (
          <ServiceError error={view.clauses.error} />
        ) : view.clauses.value.length === 0 ? (
          <EmptyState
            heading="h3"
            title={t("entities.page.noClausesTitle")}
            body={
              view.asOf === null
                ? t("entities.page.noClausesBody")
                : t("entities.page.noClausesBodyAsOf", { date: formatDate(view.asOf) })
            }
          />
        ) : (
          <ol className="flex flex-col gap-4" data-slot="mentioned-clauses">
            {view.clauses.value.map((clause) => (
              <li
                key={clause.clauseId}
                data-clause={clause.clauseId}
                className="flex flex-col gap-2 rounded-md border border-line p-4"
              >
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium text-fg">
                    {t("entities.page.clauseOf", {
                      ref: clause.clauseRef,
                      document: clause.externalRef,
                    })}
                  </span>
                  {clause.publishedAt === null ? null : (
                    <span className="text-fg-muted">{formatDate(clause.publishedAt)}</span>
                  )}
                  {clause.outOfForce ? (
                    <Badge tone="warning">{t("entities.page.outOfForce")}</Badge>
                  ) : null}
                </div>
                <p className="text-xs text-fg-muted">{clause.documentTitle}</p>
                <ClauseText clause={clause} />
                <Link
                  href={clause.href as Route}
                  className="text-sm text-primary underline-offset-2 hover:underline"
                >
                  {t("entities.page.openClause", { ref: clause.clauseRef })}
                </Link>
              </li>
            ))}
          </ol>
        )}
      </section>
      <section aria-labelledby="entity-relations" className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 id="entity-relations" className="text-lg font-semibold text-fg">
            {t("entities.page.relationsHeading")}
          </h2>
          <p className="max-w-prose text-sm text-fg-muted">{t("entities.page.relationsIntro")}</p>
        </div>
        {!view.relations.ok ? (
          <ServiceError error={view.relations.error} />
        ) : view.relations.value.length === 0 ? (
          <p className="text-sm text-fg-muted" data-slot="no-relations">
            {t("entities.page.noRelations")}
          </p>
        ) : (
          <Table data-slot="entity-relations" scrollLabel={t("entities.page.relationsRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("entities.page.relationsCaption", { count: view.relations.value.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("relations.column.from")}</TableHead>
                <TableHead>{t("relations.column.relation")}</TableHead>
                <TableHead>{t("relations.column.evidence")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.relations.value.map((relation) => (
                <TableRow key={relation.relationId} data-relation={relation.relation}>
                  <TableCell className="align-top">
                    <span className="flex flex-wrap items-center gap-2">
                      <Link
                        href={relation.from.href as Route}
                        className="font-mono text-sm text-primary underline-offset-2 hover:underline"
                      >
                        {relation.from.label ?? relation.from.ruleVersionId}
                      </Link>
                      {relation.from.status === null ? null : (
                        <RuleVersionStatusChip status={relation.from.status} />
                      )}
                    </span>
                  </TableCell>
                  <TableCell className="align-top">{humanise(relation.relation)}</TableCell>
                  <TableCell className="align-top">
                    <Link
                      href={relation.evidenceHref as Route}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {t("relations.evidence", { ref: relation.evidenceClauseRef })}
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}
