import type { Route } from "next";
import Link from "next/link";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { RuleVersionStatusChip } from "@/shared/ui/rule-version-status";
import { ServiceError } from "@/shared/ui/service-error";
import type { Part, RelationView, VersionRef } from "../model/version-page";

export interface RelationsSectionProps {
  relations: Part<{ from: readonly RelationView[]; to: readonly RelationView[] }>;
  graphHref: string;
}

function VersionLink({ version }: { version: VersionRef }) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Link
        href={version.href as Route}
        className="font-mono text-sm text-primary underline-offset-2 hover:underline"
      >
        {version.label ?? version.ruleVersionId}
      </Link>
      {version.status === null ? null : <RuleVersionStatusChip status={version.status} />}
    </span>
  );
}

function Other({ relation }: { relation: RelationView }) {
  if (relation.version !== null) return <VersionLink version={relation.version} />;
  if (relation.entity !== null) {
    const name = `${humanise(relation.entity.entityType)}: ${relation.entity.name}`;
    return relation.entity.href === null ? (
      <span>{name}</span>
    ) : (
      <Link
        href={relation.entity.href as Route}
        className="text-primary underline-offset-2 hover:underline"
      >
        {name}
      </Link>
    );
  }
  return <span className="text-fg-muted">{t("common.unknown")}</span>;
}

function Detail({ relation }: { relation: RelationView }) {
  if (relation.newDueOn === null && relation.periodLabel === null) return null;
  return (
    <span className="block text-xs text-fg-muted">
      {t("relations.deadline", {
        period: relation.periodLabel ?? t("relations.noPeriod"),
        due: relation.newDueOn === null ? t("relations.noDate") : formatDate(relation.newDueOn),
      })}
    </span>
  );
}

function RelationsTable({
  rows,
  caption,
  otherHeading,
  region,
}: {
  rows: readonly RelationView[];
  caption: string;
  otherHeading: string;
  region: string;
}) {
  return (
    <Table data-slot="relations-table" scrollLabel={region}>
      <TableCaption className="text-left text-sm text-fg-muted">{caption}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("relations.column.relation")}</TableHead>
          <TableHead>{otherHeading}</TableHead>
          <TableHead>{t("relations.column.evidence")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((relation) => (
          <TableRow key={relation.relationId} data-relation={relation.relation}>
            <TableCell className="align-top">
              {humanise(relation.relation)}
              <Detail relation={relation} />
            </TableCell>
            <TableCell className="align-top">
              <Other relation={relation} />
            </TableCell>
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
  );
}

/**
 * The version's relations (ADR-017): those it states about other versions and entities, which
 * take effect when it is published, and those other versions state about it. Each names its
 * evidence clause, opened in the document with the clause marked.
 */
export function RelationsSection({ relations, graphHref }: RelationsSectionProps) {
  return (
    <section aria-labelledby="version-relations" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="version-relations" className="text-lg font-semibold text-fg">
          {t("relations.heading")}
        </h2>
        <p className="max-w-prose text-sm text-fg-muted">{t("relations.intro")}</p>
        <p className="text-sm">
          <Link
            href={graphHref as Route}
            className="text-primary underline-offset-2 hover:underline"
          >
            {t("relations.graphLink")}
          </Link>
        </p>
      </div>
      {!relations.ok ? (
        <ServiceError error={relations.error} />
      ) : (
        <>
          {relations.value.from.length === 0 ? (
            <p className="text-sm text-fg-muted" data-slot="relations-from-empty">
              {t("relations.fromEmpty")}
            </p>
          ) : (
            <RelationsTable
              rows={relations.value.from}
              caption={t("relations.fromCaption", { count: relations.value.from.length })}
              otherHeading={t("relations.column.to")}
              region={t("relations.fromRegion")}
            />
          )}
          {relations.value.to.length === 0 ? (
            <p className="text-sm text-fg-muted" data-slot="relations-to-empty">
              {t("relations.toEmpty")}
            </p>
          ) : (
            <RelationsTable
              rows={relations.value.to}
              caption={t("relations.toCaption", { count: relations.value.to.length })}
              otherHeading={t("relations.column.from")}
              region={t("relations.toRegion")}
            />
          )}
        </>
      )}
    </section>
  );
}
