import type { Route } from "next";
import Link from "next/link";
import { Banner, Button, PageHeader, ProgressBar } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { FocusHeading } from "@/shared/ui/focus-heading";
import { OnboardingStepper } from "@/shared/ui/onboarding-stepper";
import type { QuestionStepView } from "../model/onboarding-step";
import { AnswerForm, type AnswerAction } from "./answer-form";
import { ReviewTasksTable } from "./review-tasks-table";

export interface QuestionStepProps {
  view: QuestionStepView;
  action: AnswerAction;
  /** The field names the answer form posts (the business model's ANSWER_FIELDS). */
  fields: {
    businessId: string;
    nodeId: string;
    key: string;
    asOfFy: string;
    value: string;
  };
  /** The onboarding summary, to stop here. */
  doneHref: string;
}

/**
 * The third onboarding step: one question at a time. The question is the page's h1, worded by
 * the ontology, with the node it is about and the year for a per-year question; the progress
 * bar counts what the business API counts as answered. After an answer the page renders again
 * with the next question, a status line naming what was saved, and focus on the new h1. The
 * review tasks the answers opened are listed under the form.
 */
export function QuestionStep({ view, action, fields, doneHref }: QuestionStepProps) {
  const { question, progress, saved } = view;
  return (
    <div data-slot="question-step" className="flex max-w-3xl flex-col gap-6">
      <OnboardingStepper current="questions" />
      <ProgressBar
        label={t("question.progressLabel", { name: view.businessName })}
        value={progress.answered}
        max={progress.total}
        valueText={progress.text}
      />
      {view.unsureCount > 0 ? (
        <p className="text-sm text-fg-muted" data-slot="question-unsure-count">
          {t("question.unsureCount", { count: view.unsureCount })}
        </p>
      ) : null}
      {saved === null ? null : (
        <Banner tone="success" title={t("question.saved", { label: saved.label })}>
          {saved.reviewTaskOpened ? t("question.savedReviewTask") : null}
        </Banner>
      )}
      <FocusHeading active={saved !== null} />
      {question === null ? (
        <>
          <PageHeader title={t("question.nothingLeft")} />
          <div>
            <Button asChild>
              <Link href={doneHref as Route}>{t("question.toSummary")}</Link>
            </Button>
          </div>
        </>
      ) : (
        <>
          <PageHeader
            title={question.heading}
            description={
              question.yearText === null ? question.about : `${question.about} ${question.yearText}`
            }
          />
          {question.wasUnsure ? (
            <p className="text-sm text-fg-muted">{t("question.wasUnsure")}</p>
          ) : null}
          {question.attribute === undefined ? (
            <Banner tone="warning" title={t("question.unsupportedTitle")}>
              {t("question.unsupported", { type: question.type })}
            </Banner>
          ) : (
            <AnswerForm
              key={`${question.nodeId}:${question.key}`}
              action={action}
              attribute={question.attribute}
              id="question"
              label={question.heading}
              hideLabel
              description={question.help === "" ? undefined : question.help}
              valueField={fields.value}
              hidden={{
                [fields.businessId]: view.businessId,
                [fields.nodeId]: question.nodeId,
                [fields.key]: question.key,
                [fields.asOfFy]: question.asOfFy ?? "",
              }}
            />
          )}
          <p className="text-sm">
            <Link href={doneHref as Route} className="text-primary underline">
              {t("question.stopHere")}
            </Link>
          </p>
        </>
      )}
      <section aria-labelledby="question-review-tasks" className="flex flex-col gap-3">
        <h2 id="question-review-tasks" className="text-lg font-semibold text-fg">
          {t("question.reviewTasksTitle")}
        </h2>
        {view.reviewTasks.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("question.reviewTasksNone")}</p>
        ) : (
          <ReviewTasksTable rows={view.reviewTasks} caption={t("question.reviewTasksCaption")} />
        )}
      </section>
    </div>
  );
}
