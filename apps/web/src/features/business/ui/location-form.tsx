"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useEffect, useId, useRef } from "react";
import { Banner, Button, ErrorState, Field, Input } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

/** What adding a location returned (the business model's LocationAdded, structurally). */
export interface LocationFormResult {
  id: string;
  label: string;
  name: string;
  created: boolean;
  attributesHref: string;
  snapshotHref: string;
}

export type LocationAction = (
  state: ActionState<LocationFormResult>,
  formData: FormData,
) => Promise<ActionState<LocationFormResult>>;

export interface LocationFormProps {
  action: LocationAction;
  businessId: string;
  registrationId: string;
  /** The registration's GSTIN, to name the form. */
  gstin: string;
  fields: { businessId: string; registrationId: string; label: string; name: string };
}

interface Attempt {
  state: ActionState<LocationFormResult>;
  values: Record<string, string>;
  count: number;
}

/**
 * Adds a location under one registration: a label (the branch code the location is known by
 * under its registration) and a name. The answer says whether the location is new or was
 * already there, with links to its attributes and its snapshot, since no route lists a
 * registration's locations yet.
 */
export function LocationForm({
  action,
  businessId,
  registrationId,
  gstin,
  fields,
}: LocationFormProps) {
  const id = useId();
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => ({
      state: await action(previous.state, formData),
      values: {
        [fields.label]: String(formData.get(fields.label) ?? ""),
        [fields.name]: String(formData.get(fields.name) ?? ""),
      },
      count: previous.count + 1,
    }),
    { state: idleAction<LocationFormResult>(), values: {}, count: 0 },
  );
  const { state } = attempt;
  const statusRef = useRef<HTMLDivElement>(null);
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];

  useEffect(() => {
    if (attempt.count > 0) statusRef.current?.focus();
  }, [attempt]);

  const kept = state.status === "error" ? attempt.values : {};
  const result = state.status === "ok" ? state.value : undefined;
  return (
    <form
      action={formAction}
      aria-label={t("location.formLabel", { gstin })}
      data-slot="location-form"
      className="flex flex-col gap-3"
    >
      <input type="hidden" name={fields.businessId} value={businessId} />
      <input type="hidden" name={fields.registrationId} value={registrationId} />
      <div ref={statusRef} tabIndex={-1} className="flex flex-col gap-2 outline-none">
        {problem ? (
          <ErrorState
            title={problem.title}
            detail={problem.detail}
            correlationId={problem.correlationId || undefined}
          />
        ) : null}
        {formErrors.map((message) => (
          <Banner key={message} tone="danger" title={t("location.refused")}>
            {message}
          </Banner>
        ))}
        {result === undefined ? null : (
          <Banner
            tone="success"
            title={
              result.created
                ? t("location.added", { label: result.label })
                : t("location.existing", { label: result.label })
            }
          >
            <p>
              {result.name}.{" "}
              <Link href={result.attributesHref as Route}>{t("location.attributes")}</Link>
              {" · "}
              <Link href={result.snapshotHref as Route}>{t("location.snapshot")}</Link>
            </p>
          </Banner>
        )}
      </div>
      <div className="grid max-w-xl gap-3" key={attempt.count}>
        <Field
          id={`${id}-label`}
          label={t("location.label")}
          description={t("location.labelHelp")}
          error={fieldErrorOf(state, fields.label)}
          required
        >
          <Input name={fields.label} defaultValue={kept[fields.label]} maxLength={80} />
        </Field>
        <Field
          id={`${id}-name`}
          label={t("location.name")}
          error={fieldErrorOf(state, fields.name)}
          required
        >
          <Input name={fields.name} defaultValue={kept[fields.name]} maxLength={200} />
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
          {pending ? t("location.pending") : t("location.submit")}
        </Button>
      </div>
    </form>
  );
}
