import type { Route } from "next";
import Link from "next/link";
import { Button, KeyValue, PageHeader, ProgressBar } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { OnboardingStepper } from "@/shared/ui/onboarding-stepper";
import type { DoneSummaryView, OpenItem } from "../model/onboarding-step";
import { ReviewTasksTable } from "./review-tasks-table";

export interface DoneSummaryProps {
  title: string;
  view: DoneSummaryView;
  /** Clears the skip list and returns to the questions (a plain form action). */
  revisitAction: (formData: FormData) => Promise<void>;
  businessIdField: string;
  questionsHref: string;
  businessHref: string;
}

function ItemList({ items }: { items: readonly OpenItem[] }) {
  return (
    <ul className="list-disc pl-5 text-sm text-fg">
      {items.map((item) => (
        <li key={item.id}>{t("done.item", { label: item.label, node: item.node })}</li>
      ))}
    </ul>
  );
}

/**
 * The last onboarding step: what the business's profile holds now. The counts are the
 * checklist's (answered, does not apply, not sure, not answered yet); the questions answered
 * "Not sure" can be asked again, and the review tasks the answers opened are listed with why.
 */
export function DoneSummary({
  title,
  view,
  revisitAction,
  businessIdField,
  questionsHref,
  businessHref,
}: DoneSummaryProps) {
  const gstins = view.gstins.length === 0 ? t("done.noGstin") : view.gstins.join(", ");
  return (
    <div data-slot="done-summary" className="flex max-w-3xl flex-col gap-6">
      <OnboardingStepper current="done" />
      <PageHeader
        title={title}
        description={t("done.intro", { name: view.businessName, pan: view.pan, gstins })}
      />
      <ProgressBar
        label={t("question.progressLabel", { name: view.businessName })}
        value={view.progress.answered}
        max={view.progress.total}
        valueText={view.progress.text}
      />
      <KeyValue
        items={[
          { key: "known", label: t("done.known"), value: String(view.counts.known) },
          {
            key: "not_applicable",
            label: t("done.notApplicable"),
            value: String(view.counts.not_applicable),
          },
          { key: "unsure", label: t("done.unsure"), value: String(view.counts.unsure) },
          { key: "missing", label: t("done.missing"), value: String(view.counts.missing) },
        ]}
      />
      {view.unsure.length > 0 ? (
        <section aria-labelledby="done-unsure" className="flex flex-col gap-3">
          <h2 id="done-unsure" className="text-lg font-semibold text-fg">
            {t("done.unsureTitle")}
          </h2>
          <ItemList items={view.unsure} />
          <form action={revisitAction}>
            <input type="hidden" name={businessIdField} value={view.businessId} />
            <Button type="submit" variant="secondary">
              {t("done.revisit")}
            </Button>
          </form>
        </section>
      ) : null}
      {view.missing.length > 0 ? (
        <section aria-labelledby="done-missing" className="flex flex-col gap-3">
          <h2 id="done-missing" className="text-lg font-semibold text-fg">
            {t("done.missingTitle")}
          </h2>
          <ItemList items={view.missing} />
          <div>
            <Button asChild variant="secondary">
              <Link href={questionsHref as Route}>{t("done.continue")}</Link>
            </Button>
          </div>
        </section>
      ) : null}
      <section aria-labelledby="done-review-tasks" className="flex flex-col gap-3">
        <h2 id="done-review-tasks" className="text-lg font-semibold text-fg">
          {t("done.reviewTasksTitle")}
        </h2>
        {view.reviewTasks.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("question.reviewTasksNone")}</p>
        ) : (
          <ReviewTasksTable rows={view.reviewTasks} caption={t("done.reviewTasksCaption")} />
        )}
      </section>
      <div>
        <Button asChild>
          <Link href={businessHref as Route}>{t("done.openBusiness")}</Link>
        </Button>
      </div>
    </div>
  );
}
