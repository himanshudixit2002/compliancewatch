import {
  Badge,
  Banner,
  EmptyState,
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
import type { KeyValueItem } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import type { AttributeRow, LevelSection, OntologyBrowserView, UsageNote } from "../model/browser";

export interface OntologyViewProps {
  title: string;
  crumbs: readonly Crumb[];
  view: OntologyBrowserView;
  usage: UsageNote;
}

function Muted({ children }: { children: string }) {
  return <span className="text-xs text-fg-muted">{children}</span>;
}

function AttributeCell({ row }: { row: AttributeRow }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <code className="font-mono text-xs font-medium text-fg">{row.key}</code>
      <Muted>{row.typeLabel}</Muted>
      <Muted>{row.sourceLabel}</Muted>
      {row.perFinancialYear ? <Badge tone="info">{t("ontology.perYear")}</Badge> : null}
    </div>
  );
}

function QuestionCell({ row }: { row: AttributeRow }) {
  return (
    <div className="flex flex-col gap-1">
      {row.question === "" ? (
        <span className="text-fg-muted">{t("ontology.notAsked")}</span>
      ) : (
        <span className="text-fg">{row.question}</span>
      )}
      {row.help === "" ? null : <Muted>{row.help}</Muted>}
      <Muted>{t("ontology.meaning", { definition: row.definition })}</Muted>
    </div>
  );
}

function ValuesCell({ row }: { row: AttributeRow }) {
  return (
    <div className="flex flex-col gap-1">
      {row.options.length > 0 ? (
        <ul className="flex flex-col gap-0.5">
          {row.options.map((option) => (
            <li key={option.value}>
              <span className="text-fg">{option.label}</span>{" "}
              <code className="font-mono text-xs text-fg-muted">{option.value}</code>
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-fg">{row.range ?? t("ontology.anyValue")}</span>
      )}
      {row.example === null ? null : <Muted>{t("ontology.example", { value: row.example })}</Muted>}
    </div>
  );
}

function OperatorsCell({ row }: { row: AttributeRow }) {
  if (row.operators.length === 0) return <span className="text-fg-muted">{t("common.none")}</span>;
  return <code className="font-mono text-xs text-fg">{row.operators.join(", ")}</code>;
}

function LevelTable({ section }: { section: LevelSection }) {
  const headingId = `ontology-level-${section.level}`;
  return (
    <section aria-labelledby={headingId} data-level={section.level} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-lg font-semibold text-fg">
        {section.label}
      </h2>
      <Table scrollLabel={t("ontology.tableRegion", { level: section.label })}>
        <TableCaption className="text-left text-sm text-fg-muted">
          {t("ontology.caption", { count: section.attributes.length })}
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>{t("ontology.column.attribute")}</TableHead>
            <TableHead>{t("ontology.column.question")}</TableHead>
            <TableHead>{t("ontology.column.values")}</TableHead>
            <TableHead>{t("ontology.column.operators")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {section.attributes.map((row) => (
            <TableRow key={row.key} data-attribute={row.key}>
              <TableCell className="align-top">
                <AttributeCell row={row} />
              </TableCell>
              <TableCell className="min-w-72 align-top whitespace-normal">
                <QuestionCell row={row} />
              </TableCell>
              <TableCell className="min-w-56 align-top whitespace-normal">
                <ValuesCell row={row} />
              </TableCell>
              <TableCell className="align-top whitespace-normal">
                <OperatorsCell row={row} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

/**
 * The ontology browser: the version facts, a note on what waits (the usage counts, from their
 * registry entry), any attribute the web app cannot show, then one table per level of the
 * business hierarchy with each attribute's question, help, meaning, allowed values, example and
 * the operators a rule may use on it. Read-only: the ontology changes with a release.
 */
export function OntologyView({ title, crumbs, view, usage }: OntologyViewProps) {
  const facts: KeyValueItem[] = [
    {
      key: "version",
      label: t("ontology.fact.version"),
      value: <code className="font-mono text-xs">{view.version}</code>,
    },
    {
      key: "wording",
      label: t("ontology.fact.wording"),
      value: t("ontology.fact.wordingValue", {
        version: view.wordingVersion,
        language: view.language,
      }),
    },
    {
      key: "review",
      label: t("ontology.fact.review"),
      value: view.wordingReviewed ? (
        <Badge tone="success">{t("ontology.reviewed")}</Badge>
      ) : (
        <Badge tone="warning">{t("ontology.needsReview")}</Badge>
      ),
    },
    { key: "attributes", label: t("ontology.fact.attributes"), value: String(view.total) },
  ];
  return (
    <div data-slot="ontology" className="flex flex-col gap-6">
      <PageHeader
        title={title}
        description={t("ontology.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <KeyValue items={facts} aria-label={t("ontology.facts")} />
      <Banner tone="info" title={t("ontology.usageTitle", { title: usage.title })}>
        <p>{t("ontology.usageBody")}</p>
        <ul data-slot="usage-awaits" className="mt-1 flex flex-col gap-0.5">
          {usage.waitingFor.map((item) => (
            <li key={`${item.method} ${item.path}`}>
              <code className="font-mono text-xs">{`${item.method} ${item.path}`}</code> (
              {item.owner})
            </li>
          ))}
        </ul>
      </Banner>
      {view.unsupported.length > 0 ? (
        <Banner tone="warning" title={t("ontology.unsupportedTitle")}>
          {t("ontology.unsupportedBody", { keys: view.unsupported.join(", ") })}
        </Banner>
      ) : null}
      {view.sections.length === 0 ? (
        <EmptyState title={t("ontology.emptyTitle")} body={t("ontology.emptyBody")} />
      ) : (
        view.sections.map((section) => <LevelTable key={section.level} section={section} />)
      )}
    </div>
  );
}
