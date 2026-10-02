"use client";

import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { useActionState, useEffect, useId, useRef } from "react";
import { Banner, Button, ErrorState, Field, Input } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

/** What adding a GSTIN returned (the business model's RegistrationAddedResult, structurally). */
export interface RegistrationFormResult {
  registrationId: string;
  gstin: string;
  name: string;
  created: boolean;
  lookedUp: boolean;
  applied: readonly string[];
  attributesHref: string;
  reviewTasksHref: string;
}

export type RegistrationAction = (
  state: ActionState<RegistrationFormResult>,
  formData: FormData,
) => Promise<ActionState<RegistrationFormResult>>;

export interface RegistrationFormProps {
  action: RegistrationAction;
  businessId: string;
  businessName: string;
  /** The business's PAN, which every GSTIN of it carries. */
  pan: string;
  /** The hidden Idempotency-Key input the page rendered for this form. */
  idempotencyInput: ReactNode;
  fields: { businessId: string; gstin: string; name: string };
  /** The profile page again, for another GSTIN: loaded afresh, so with a new key. */
  againHref: string;
}

interface Attempt {
  state: ActionState<RegistrationFormResult>;
  values: Record<string, string>;
  count: number;
}

function lookupLine(result: RegistrationFormResult): string {
  if (!result.lookedUp) return t("registration.notLookedUp");
  return result.applied.length === 0
    ? t("registration.lookedUpNothing")
    : t("registration.lookedUp", { attributes: result.applied.join(", ") });
}

/**
 * Adds another GSTIN registration to the business: the GSTIN (it must carry the business's PAN)
 * and an optional name for the registration. The answer replaces the form: the GSTIN, whether it
 * is new, what the GSTIN lookup filled in or that a review task was opened to verify it, with
 * links to its attributes and the review tasks. "Add another GSTIN" loads the page afresh, so the
 * next form carries a new Idempotency-Key. A refused submit keeps what was typed and moves focus
 * to the problem; the button is disabled and busy while the action runs.
 */
export function RegistrationForm({
  action,
  businessId,
  businessName,
  pan,
  idempotencyInput,
  fields,
  againHref,
}: RegistrationFormProps) {
  const id = useId();
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      values: {
        [fields.gstin]: String(formData.get(fields.gstin) ?? ""),
        [fields.name]: String(formData.get(fields.name) ?? ""),
      },
      count: previous.count + 1,
    }),
    { state: idleAction<RegistrationFormResult>(), values: {}, count: 0 },
  );
  const { state } = attempt;
  const statusRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (attempt.count > 0) statusRef.current?.focus();
  }, [attempt]);

  if (state.status === "ok" && state.value !== undefined) {
    const result = state.value;
    return (
      <div
        ref={statusRef}
        tabIndex={-1}
        data-slot="registration-result"
        className="flex flex-col gap-3 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus/50"
      >
        <Banner
          tone="success"
          title={
            result.created
              ? t("registration.added", { gstin: result.gstin })
              : t("registration.existing", { gstin: result.gstin })
          }
        >
          <p>{lookupLine(result)}</p>
          <p>
            <Link href={result.attributesHref as Route}>{t("registration.attributes")}</Link>
            {" · "}
            <Link href={result.reviewTasksHref as Route}>{t("registration.reviewTasks")}</Link>
          </p>
        </Banner>
        <div>
          <Button asChild variant="secondary" size="sm">
            {/* A document load, not a client navigation: the page renders again with a new
                Idempotency-Key and an empty form. */}
            <a href={againHref}>{t("registration.another")}</a>
          </Button>
        </div>
      </div>
    );
  }

  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const kept = state.status === "error" ? attempt.values : {};
  return (
    <form
      action={formAction}
      aria-label={t("registration.formLabel", { name: businessName })}
      data-slot="registration-form"
      className="flex flex-col gap-3"
    >
      {idempotencyInput}
      <input type="hidden" name={fields.businessId} value={businessId} />
      <div ref={statusRef} tabIndex={-1} className="flex flex-col gap-2 outline-none">
        {problem ? (
          <ErrorState
            title={problem.title}
            detail={problem.detail}
            correlationId={problem.correlationId || undefined}
          />
        ) : null}
        {formErrors.map((message) => (
          <Banner key={message} tone="danger" title={t("registration.refused")}>
            {message}
          </Banner>
        ))}
      </div>
      <div className="grid max-w-xl gap-3" key={attempt.count}>
        <Field
          id={`${id}-gstin`}
          label={t("registration.gstin")}
          description={t("registration.gstinHelp", { pan })}
          error={fieldErrorOf(state, fields.gstin)}
          required
        >
          <Input
            name={fields.gstin}
            defaultValue={kept[fields.gstin]}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={20}
          />
        </Field>
        <Field
          id={`${id}-name`}
          label={t("businessStep.registrationName")}
          description={t("businessStep.registrationNameHelp")}
          error={fieldErrorOf(state, fields.name)}
        >
          <Input
            name={fields.name}
            defaultValue={kept[fields.name]}
            autoComplete="off"
            maxLength={200}
          />
        </Field>
      </div>
      <div>
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          disabled={pending}
          aria-busy={pending || undefined}
        >
          {pending ? t("registration.pending") : t("registration.submit")}
        </Button>
      </div>
    </form>
  );
}
