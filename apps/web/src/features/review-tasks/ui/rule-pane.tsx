import type { Route } from "next";
import Link from "next/link";
import { Banner, KeyValue } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { SpecificationView } from "@/shared/ui/specification";
import type { WriteAction } from "@/shared/ui/write-outcome";
import type { DraftContentView, RulePane as RulePaneModel } from "../model/workbench";
import { ClaimPanel } from "./claim-panel";
import { DecidePanel } from "./decide-panel";
import { DraftPanel } from "./draft-panel";
import { EditPanel } from "./edit-panel";
import type { AccessView, EditorOntology, WriteResult } from "./form-shared";

export interface RuleActions {
  claim: WriteAction<WriteResult>;
  draft: WriteAction<WriteResult>;
  edit: WriteAction<WriteResult>;
  decide: WriteAction<WriteResult>;
}

export interface RulePaneProps {
  pane: RulePaneModel;
  candidateTask: boolean;
  access: AccessView;
  ontology: EditorOntology | null;
  /** The bound actions; null when the session may not send any (the access says why). */
  actions: RuleActions | null;
}

function DraftContent({ draft }: { draft: DraftContentView }) {
  return (
    <div className="flex flex-col gap-3" data-slot="draft-content">
      <KeyValue
        layout="stack"
        items={[
          { key: "rule", label: t("workbench.draftView.rule"), value: draft.ruleLabel },
          { key: "title", label: t("workbench.field.title"), value: draft.title },
          {
            key: "summary",
            label: t("workbench.field.summary"),
            value: draft.summary === "" ? t("workbench.diff.notStated") : draft.summary,
          },
          {
            key: "applies",
            label: t("workbench.draftView.appliesAt"),
            value: t("workbench.draftView.appliesValue", {
              level: draft.level,
              regulator: draft.regulator,
            }),
          },
          { key: "period", label: t("workbench.diff.field.period"), value: draft.period },
          {
            key: "recurrence",
            label: t("workbench.diff.field.recurrence"),
            value: draft.recurrence,
          },
          {
            key: "obligation",
            label: t("workbench.diff.field.template"),
            value:
              draft.template === null ? (
                t("workbench.draftView.templateUnread")
              ) : (
                <div className="flex flex-col gap-1">
                  <span className="font-medium">{draft.template.title}</span>
                  {draft.template.steps.length === 0 ? null : (
                    <ol className="ml-5 list-decimal">
                      {draft.template.steps.map((step, index) => (
                        <li key={index}>{step}</li>
                      ))}
                    </ol>
                  )}
                  {draft.template.due === null ? null : <span>{draft.template.due}</span>}
                  <span>{t("workbench.diff.evidence", { evidence: draft.template.evidence })}</span>
                </div>
              ),
          },
          {
            key: "condition",
            label: t("workbench.diff.field.specification"),
            value:
              draft.specification === null ? (
                t("ruleVersion.spec.none")
              ) : (
                <SpecificationView line={draft.specification} />
              ),
          },
          {
            key: "todo",
            label: t("workbench.diff.field.todo"),
            value:
              draft.todo.length === 0 ? (
                t("workbench.draftView.noQuestions")
              ) : (
                <ul className="ml-5 list-disc" data-slot="draft-questions">
                  {draft.todo.map((question, index) => (
                    <li key={index}>{question}</li>
                  ))}
                </ul>
              ),
          },
          {
            key: "source",
            label: t("workbench.draftView.source"),
            value:
              draft.source.instrument === "" && draft.source.reference === ""
                ? t("workbench.diff.notStated")
                : [draft.source.instrument, draft.source.reference]
                    .filter((part) => part !== "")
                    .join(", "),
          },
        ]}
      />
    </div>
  );
}

/**
 * The rule pane: the draft in words, then what the task's state allows the signed-in analyst:
 * claiming it, drafting a version from the candidate, editing the draft, and deciding, with the
 * round's approvals. After an approval the version is published from its own page (W5); this pane
 * links there and publishes nothing.
 */
export function RulePane({ pane, candidateTask, access, ontology, actions }: RulePaneProps) {
  return (
    <section
      aria-labelledby="pane-rule"
      data-slot="rule-pane"
      className="flex min-w-0 flex-col gap-5"
    >
      <h2 id="pane-rule" className="text-lg font-semibold text-fg">
        {t("workbench.rule.heading")}
      </h2>
      {pane.draft === null ? (
        <p className="text-sm text-fg-muted" data-slot="no-draft">
          {t("workbench.rule.noDraft")}
        </p>
      ) : (
        <DraftContent draft={pane.draft} />
      )}
      {pane.versionHref === null ? null : (
        <p className="text-sm">
          <Link
            href={pane.versionHref as Route}
            className="text-primary underline-offset-2 hover:underline"
          >
            {t("workbench.rule.versionPage")}
          </Link>
        </p>
      )}
      {pane.publishHref === null ? null : (
        <Banner tone="success" title={t("workbench.rule.approvedTitle")} data-slot="publish-note">
          <Link
            href={pane.publishHref as Route}
            className="text-primary underline-offset-2 hover:underline"
          >
            {t("workbench.publishLink")}
          </Link>
        </Banner>
      )}
      {access.allowed || actions !== null ? null : (
        <Banner tone="warning" title={access.title} data-slot="rule-access">
          {access.detail ?? t("workbench.rule.accessDetail")}
        </Banner>
      )}
      {actions === null ? null : (
        <>
          <ClaimPanel key="claim" action={actions.claim} claim={pane.claim} />
          {candidateTask ? (
            <DraftPanel
              key="draft"
              action={actions.draft}
              form={pane.draftForm}
              blocked={pane.draftBlocked}
              ontology={ontology}
            />
          ) : null}
          {pane.draft === null ? null : (
            <EditPanel
              key="edit"
              action={actions.edit}
              form={pane.edit}
              blocked={pane.editBlocked}
              ontology={ontology}
            />
          )}
          <DecidePanel
            key="decide"
            action={actions.decide}
            view={pane.decide}
            approvals={pane.approvals}
          />
        </>
      )}
    </section>
  );
}
