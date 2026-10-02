import { Button } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

/**
 * The three ways to answer an attribute, as the submit buttons of its form: Save stores the
 * value (state known), Not sure stores no value (state unsure; onboarding asks again later),
 * and Does not apply stores no value (state not_applicable), which opens a review task for an
 * analyst, as the line under the buttons says. Each button submits `state=<value>`, so the
 * action reads `formData.get(name)`. While the action runs every button is disabled and busy.
 */
export const ANSWER_STATE_FIELD = "state";

export interface AnswerButtonsProps {
  /** The form field the chosen state is submitted under. */
  name?: string;
  pending?: boolean;
  /** Prefix for the hint's id. */
  id: string;
  /** Leaves out Not sure and Does not apply where only a value makes sense. */
  valueOnly?: boolean;
}

export function AnswerButtons({
  name = ANSWER_STATE_FIELD,
  pending = false,
  id,
  valueOnly = false,
}: AnswerButtonsProps) {
  const hintId = `${id}-not-applicable-hint`;
  const busy = pending || undefined;
  return (
    <div data-slot="answer-buttons" className="grid gap-2">
      <div role="group" aria-label={t("answer.actions")} className="flex flex-wrap gap-2">
        <Button type="submit" name={name} value="known" disabled={pending} aria-busy={busy}>
          {pending ? t("answer.pending") : t("answer.save")}
        </Button>
        {valueOnly ? null : (
          <>
            <Button
              type="submit"
              variant="secondary"
              name={name}
              value="unsure"
              disabled={pending}
              aria-busy={busy}
            >
              {t("answer.unsure")}
            </Button>
            <Button
              type="submit"
              variant="secondary"
              name={name}
              value="not_applicable"
              disabled={pending}
              aria-busy={busy}
              aria-describedby={hintId}
            >
              {t("answer.notApplicable")}
            </Button>
          </>
        )}
      </div>
      {valueOnly ? null : (
        <p id={hintId} className="text-sm text-fg-muted">
          {t("answer.notApplicableHelp")}
        </p>
      )}
    </div>
  );
}
