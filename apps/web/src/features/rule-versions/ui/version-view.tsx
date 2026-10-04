import type { ReactNode } from "react";
import { Banner, JsonView, KeyValue, PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { RuleVersionStatusChip, SeedStatusChip } from "@/shared/ui/rule-version-status";
import { ServiceError } from "@/shared/ui/service-error";
import type { VersionPageView } from "../model/version-page";
import { CitationsSection } from "./citations-section";
import type { SaveCitationsAction } from "./citations-editor";
import { RelationsSection } from "./relations-section";
import { SpecificationView } from "./specification-view";
import { WorkflowPanel, type TakeStepAction } from "./workflow-panel";

export interface VersionViewProps {
  view: VersionPageView;
  crumbs: readonly Crumb[];
  citeAction: SaveCitationsAction;
  stepAction: TakeStepAction;
  sessionUserId: string;
  sessionName: string;
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-lg font-semibold text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

/**
 * One rule version for the analyst who reviews it: what it says (the summary, the condition in
 * words, the obligation and how it recurs, the cited instrument), its period and status, whether
 * an analyst has reviewed it (a clear warning while it needs review), the questions still open,
 * its citations with their verification, its relations, and the publish workflow.
 */
export function VersionView({
  view,
  crumbs,
  citeAction,
  stepAction,
  sessionUserId,
  sessionName,
}: VersionViewProps) {
  const { version } = view;
  const template = version.obligationTemplate;
  const recurrence = version.recurrence;
  return (
    <div data-slot="rule-version" className="flex max-w-5xl flex-col gap-8">
      <PageHeader
        title={version.title}
        description={t("ruleVersion.intro", { rule: version.ruleKey, version: version.version })}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      {version.needsReview ? (
        <Banner tone="warning" title={t("ruleVersion.notReviewedTitle")} data-notice="not-reviewed">
          {t("ruleVersion.notReviewedBody")}
        </Banner>
      ) : null}
      <KeyValue
        data-slot="version-facts"
        items={[
          {
            key: "rule",
            label: t("ruleVersion.fact.rule"),
            value: <code className="font-mono text-sm">{version.ruleKey}</code>,
          },
          { key: "version", label: t("ruleVersion.fact.version"), value: String(version.version) },
          {
            key: "status",
            label: t("ruleVersion.fact.status"),
            value: <RuleVersionStatusChip status={version.status} />,
          },
          {
            key: "seed",
            label: t("ruleVersion.fact.review"),
            value: <SeedStatusChip seedStatus={version.seedStatus} />,
          },
          { key: "regulator", label: t("ruleVersion.fact.regulator"), value: version.regulator },
          { key: "level", label: t("ruleVersion.fact.level"), value: humanise(version.level) },
          {
            key: "from",
            label: t("ruleVersion.fact.effectiveFrom"),
            value: formatDate(version.effectiveFrom),
          },
          {
            key: "to",
            label: t("ruleVersion.fact.effectiveTo"),
            value:
              version.effectiveTo === null
                ? t("ruleVersions.openEnded")
                : formatDate(version.effectiveTo),
          },
          {
            key: "published",
            label: t("ruleVersion.fact.published"),
            value:
              version.publishedAt === null
                ? t("ruleVersions.notPublished")
                : formatDateTime(version.publishedAt),
          },
          {
            key: "impact",
            label: t("ruleVersion.fact.highImpact"),
            value: version.highImpact
              ? t("ruleVersion.highImpactYes")
              : t("ruleVersion.highImpactNo"),
          },
          {
            key: "id",
            label: t("ruleVersion.fact.id"),
            value: <code className="font-mono text-xs">{version.ruleVersionId}</code>,
            copy: version.ruleVersionId,
          },
        ]}
      />
      <Section id="version-summary" title={t("ruleVersion.summaryHeading")}>
        <p className="max-w-prose text-sm text-fg">{version.summary}</p>
      </Section>
      <Section id="version-condition" title={t("ruleVersion.conditionHeading")}>
        {view.ontologyError === null ? null : (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-fg-muted">{t("ruleVersion.spec.ontologyMissing")}</p>
            <ServiceError error={view.ontologyError} />
          </div>
        )}
        {view.specification === null ? (
          <p className="text-sm text-fg-muted">{t("ruleVersion.spec.none")}</p>
        ) : (
          <SpecificationView line={view.specification} />
        )}
      </Section>
      <Section id="version-obligation" title={t("ruleVersion.obligationHeading")}>
        {template === null ? (
          <p className="text-sm text-fg-muted">{t("ruleVersion.obligationUnread")}</p>
        ) : (
          <div className="flex flex-col gap-3 text-sm">
            <p className="font-medium text-fg">{template.title}</p>
            {template.steps.length === 0 ? null : (
              <ol className="ml-5 flex list-decimal flex-col gap-1 text-fg">
                {template.steps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            )}
            <KeyValue
              items={[
                {
                  key: "due",
                  label: t("ruleVersion.fact.due"),
                  value:
                    recurrence === null
                      ? template.dueInDays === null
                        ? t("common.none")
                        : t("ruleVersion.dueInDays", { days: template.dueInDays })
                      : t("ruleVersion.recurs", {
                          frequency: humanise(recurrence.frequency),
                          day: recurrence.dueDay ?? "-",
                          offset: recurrence.dueMonthOffset ?? "-",
                        }),
                },
                {
                  key: "evidence",
                  label: t("ruleVersion.fact.evidence"),
                  value:
                    template.evidenceType === null
                      ? t("common.none")
                      : humanise(template.evidenceType),
                },
              ]}
            />
          </div>
        )}
      </Section>
      <Section id="version-source" title={t("ruleVersion.sourceHeading")}>
        <KeyValue
          items={[
            {
              key: "instrument",
              label: t("ruleVersion.fact.instrument"),
              value: version.source.instrument || t("common.none"),
            },
            {
              key: "reference",
              label: t("ruleVersion.fact.reference"),
              value: version.source.reference || t("common.none"),
            },
            ...(version.source.note === ""
              ? []
              : [{ key: "note", label: t("ruleVersion.fact.note"), value: version.source.note }]),
            ...(version.source.url === ""
              ? []
              : [
                  {
                    key: "url",
                    label: t("ruleVersion.fact.url"),
                    value: (
                      <a
                        href={version.source.url}
                        target="_blank"
                        rel="noreferrer"
                        className="break-all text-primary underline-offset-2 hover:underline"
                      >
                        {version.source.url} {t("ruleVersion.opensInNewTab")}
                      </a>
                    ),
                  },
                ]),
          ]}
        />
      </Section>
      <Section id="version-questions" title={t("ruleVersion.questionsHeading")}>
        {version.todo.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("ruleVersion.noQuestions")}</p>
        ) : (
          <ul className="ml-5 flex list-disc flex-col gap-1 text-sm text-fg" data-slot="questions">
            {version.todo.map((question, index) => (
              <li key={index}>{question}</li>
            ))}
          </ul>
        )}
      </Section>
      <CitationsSection
        citations={view.citations}
        canCite={view.canCite}
        access={view.access}
        action={citeAction}
      />
      <RelationsSection relations={view.relations} graphHref={view.graphHref} />
      <WorkflowPanel
        action={stepAction}
        steps={view.steps}
        access={view.access}
        version={version.version}
        highImpact={version.highImpact}
        sessionUserId={sessionUserId}
        sessionName={sessionName}
      />
      <details className="text-sm" data-slot="as-stored">
        <summary className="cursor-pointer text-primary">{t("ruleVersion.asStored")}</summary>
        <JsonView
          className="mt-2"
          label={t("ruleVersion.asStoredLabel")}
          value={version.stored}
          openDepth={2}
        />
      </details>
    </div>
  );
}
