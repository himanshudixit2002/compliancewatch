"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import {
  Banner,
  Button,
  ErrorState,
  Field,
  Input,
  KeyValue,
  Label,
  RadioGroup,
  RadioGroupItem,
  describedBy,
} from "@compliancewatch/ui";
import { BILLING_DISABLED } from "@/entities/billing/types";
import { isProblemOf } from "@/entities/problem/mappers";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";

/** What the action returns on success (the billing model's SubscriptionView, structurally). */
export interface SubscribeResult {
  planName: string;
  status: string;
  providerSubscriptionId: string;
  startedAt: string;
  checkoutUrl: string | null;
}

export type SubscribeAction = (
  state: ActionState<SubscribeResult>,
  formData: FormData,
) => Promise<ActionState<SubscribeResult>>;

export interface SubscribeFormProps {
  action: SubscribeAction;
  plans: readonly { key: string; name: string; price: string; period: string }[];
  /** The fields' names; without `quantity` the form asks for none and sends none. */
  fields: { plan: string; email: string; name: string; quantity?: string };
  /** Mints an Idempotency-Key (tests); a random UUID by default. */
  newKey?: () => string;
}

interface Submitted {
  plan: string;
  email: string;
  name: string;
  quantity: string;
}

interface Attempt {
  state: ActionState<SubscribeResult>;
  /** What was submitted, put back after a refusal (React resets a form after its action). */
  submitted: Submitted;
  count: number;
  /** The Idempotency-Key the last submission carried. */
  key?: string;
}

const EMPTY: Submitted = { plan: "", email: "", name: "", quantity: "" };

function sameValues(a: Submitted, b: Submitted): boolean {
  return a.plan === b.plan && a.email === b.email && a.name === b.name && a.quantity === b.quantity;
}

/**
 * The key a submission carries: the previous one while the same values are sent again after a
 * failure (a retry of the same attempt, which the service answers once), a new one after a
 * success or when the values changed (a new attempt).
 */
function keyFor(previous: Attempt, submitted: Submitted, newKey: () => string): string {
  const retry =
    previous.key !== undefined &&
    previous.count > 0 &&
    previous.state.status !== "ok" &&
    sameValues(previous.submitted, submitted);
  return retry && previous.key !== undefined ? previous.key : newKey();
}

/**
 * Starts a subscription: the plan, and the billing contact's email and name, which go to the
 * provider. Payment details are never asked for here; the provider's checkout page takes them.
 * The answer is shown under the form: the subscription with the link to that checkout page, the
 * plain "billing is not connected" state when the service has no provider (nothing was started,
 * nothing charged; the reference is the request id), or the problem and the fields to fix.
 *
 * Each submission carries an Idempotency-Key the form mints: kept while the same values are sent
 * again after a failure, so a retry starts at most one subscription with the provider, and
 * replaced after a success or once the values change, so the next subscription is a new request
 * rather than a key the service would refuse as reused.
 */
export function SubscribeForm({
  action,
  plans,
  fields,
  newKey = () => crypto.randomUUID(),
}: SubscribeFormProps) {
  const id = useId();
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => {
      const read = (name: string | undefined) => {
        const value = name === undefined ? null : formData.get(name);
        return typeof value === "string" ? value : "";
      };
      const submitted: Submitted = {
        plan: read(fields.plan),
        email: read(fields.email),
        name: read(fields.name),
        quantity: read(fields.quantity),
      };
      const key = keyFor(previous, submitted, newKey);
      formData.set(IDEMPOTENCY_KEY_FIELD, key);
      return {
        state: await action(previous.state, formData),
        submitted,
        count: previous.count + 1,
        key,
      };
    },
    {
      state: idleAction<SubscribeResult>(),
      submitted: { ...EMPTY, plan: plans[0]?.key ?? "" },
      count: 0,
    },
  );
  const { state } = attempt;
  const resultRef = useRef<HTMLDivElement>(null);

  const kept: Submitted =
    state.status === "error" ? attempt.submitted : { ...EMPTY, plan: plans[0]?.key ?? "" };

  // After an answer, focus moves to it: the subscription, the billing state or the problem.
  // A refusal on the fields alone leaves focus where it is, next to the messages.
  useEffect(() => {
    const answer = attempt.state;
    const shown =
      answer.status === "ok" ||
      (answer.status === "error" &&
        (answer.problem !== undefined || (answer.formErrors?.length ?? 0) > 0));
    if (attempt.count > 0 && shown) resultRef.current?.focus();
  }, [attempt]);
  const problem = state.status === "error" ? state.problem : undefined;
  const disabled = problem !== undefined && isProblemOf(problem, BILLING_DISABLED);
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const planError = fieldErrorOf(state, fields.plan);
  const planLabel = `${id}-plan-label`;
  const planErrorId = `${id}-plan-error`;
  const result = state.status === "ok" ? state.value : undefined;
  return (
    <div data-slot="subscribe" className="flex flex-col gap-4">
      <form
        action={formAction}
        noValidate
        aria-label={t("billing.formLabel")}
        data-slot="subscribe-form"
        className="flex max-w-xl flex-col gap-4"
      >
        <div key={attempt.count} className="contents">
          <div className="grid gap-2">
            <span id={planLabel} className="text-sm font-medium text-fg">
              {t("billing.plan")}
            </span>
            <RadioGroup
              name={fields.plan}
              defaultValue={kept.plan}
              aria-labelledby={planLabel}
              aria-describedby={describedBy(planError ? planErrorId : undefined)}
              aria-invalid={planError ? true : undefined}
              className="gap-2"
            >
              {plans.map((plan) => (
                <div key={plan.key} className="flex items-center gap-2">
                  <RadioGroupItem id={`${id}-plan-${plan.key}`} value={plan.key} />
                  <Label htmlFor={`${id}-plan-${plan.key}`}>
                    {t("billing.planOption", {
                      name: plan.name,
                      price: plan.price,
                      period: plan.period,
                    })}
                  </Label>
                </div>
              ))}
            </RadioGroup>
            {planError ? (
              <p id={planErrorId} data-slot="field-error" className="text-sm text-danger">
                {planError}
              </p>
            ) : null}
          </div>
          <Field
            id={`${id}-email`}
            label={t("billing.email")}
            description={t("billing.emailHelp")}
            error={fieldErrorOf(state, fields.email)}
            required
          >
            <Input
              name={fields.email}
              type="email"
              autoComplete="email"
              maxLength={254}
              defaultValue={kept.email}
            />
          </Field>
          <Field
            id={`${id}-name`}
            label={t("billing.name")}
            description={t("billing.nameHelp")}
            error={fieldErrorOf(state, fields.name)}
            required
          >
            <Input
              name={fields.name}
              autoComplete="organization"
              maxLength={200}
              defaultValue={kept.name}
            />
          </Field>
          {fields.quantity === undefined ? null : (
            <Field
              id={`${id}-quantity`}
              label={t("billing.quantity")}
              description={t("billing.quantityHelp")}
              error={fieldErrorOf(state, fields.quantity)}
            >
              <Input
                name={fields.quantity}
                type="number"
                inputMode="numeric"
                min={1}
                max={1000}
                step={1}
                defaultValue={kept.quantity}
              />
            </Field>
          )}
        </div>
        <p className="text-sm text-fg-muted">{t("billing.noCardData")}</p>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("billing.pending") : t("billing.submit")}
          </Button>
        </div>
      </form>
      <div
        ref={resultRef}
        tabIndex={-1}
        data-slot="subscribe-result"
        className="flex max-w-xl flex-col gap-3 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus/50"
      >
        {disabled ? (
          <Banner tone="info" title={t("billing.disabledTitle")} data-slot="billing-disabled">
            <p>{t("billing.disabled")}</p>
            {problem?.correlationId ? (
              <p className="mt-1 text-xs">
                {t("error.reference")}: <code>{problem.correlationId}</code>
              </p>
            ) : null}
          </Banner>
        ) : null}
        {result === undefined ? null : (
          <Banner tone="success" title={t("billing.started")} data-slot="subscription">
            <KeyValue
              items={[
                { key: "plan", label: t("billing.field.plan"), value: result.planName },
                { key: "status", label: t("billing.field.status"), value: result.status },
                {
                  key: "id",
                  label: t("billing.field.id"),
                  value: <code>{result.providerSubscriptionId}</code>,
                },
                { key: "started", label: t("billing.field.started"), value: result.startedAt },
              ]}
            />
            <p className="mt-2">
              {result.checkoutUrl === null ? (
                t("billing.noCheckout")
              ) : (
                <a
                  href={result.checkoutUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary underline"
                >
                  {t("billing.checkout")}
                </a>
              )}
            </p>
          </Banner>
        )}
        {problem !== undefined && !disabled ? (
          <ErrorState
            title={problem.title}
            detail={problem.detail}
            correlationId={problem.correlationId || undefined}
          />
        ) : null}
        {formErrors.length > 0 ? (
          <Banner tone="danger" title={t("billing.refused")}>
            <ul>
              {formErrors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </Banner>
        ) : null}
      </div>
    </div>
  );
}
