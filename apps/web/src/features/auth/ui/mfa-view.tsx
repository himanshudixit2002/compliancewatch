"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useEffect, useId, useRef } from "react";
import { Banner, Button, ErrorState, Field, Input, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

/** A factor as the provider lists it (the port's MfaFactor, structurally). */
export interface MfaFactorView {
  id: string;
  status: "verified" | "unverified";
  friendlyName: string;
}

export interface MfaEnrolmentView {
  factorId: string;
  qrSvg: string;
  secret: string;
}

/** What the actions answer (the actions' MfaView, structurally). */
export interface MfaActionView {
  enrolment?: MfaEnrolmentView;
}

export type MfaAction = (
  state: ActionState<MfaActionView>,
  formData: FormData,
) => Promise<ActionState<MfaActionView>>;

export interface MfaFields {
  code: string;
  factorId: string;
  friendlyName: string;
  next: string;
}

export interface MfaViewProps {
  /** `confirm`: one button asserts the factor (the fake adapter); `totp`: an authenticator app. */
  mode: "confirm" | "totp";
  /** Who is here: a signed-in person, a pending sign-in, or nobody. */
  who: "session" | "pending" | "anonymous";
  /** The roles need a second factor before they may continue. */
  required: boolean;
  /** The session already carries a verified second factor. */
  verified: boolean;
  /** Which roles ask for it, as labels, to say why. */
  requiringRoles: readonly string[];
  factors: readonly MfaFactorView[];
  verify: MfaAction;
  enrol: MfaAction;
  remove: MfaAction;
  fields: MfaFields;
  next?: string;
  signInHref: string;
  accountHref: string;
  codeLength: number;
}

interface Attempt {
  state: ActionState<MfaActionView>;
  /** The enrolment under way, kept while its code is refused. */
  enrolment?: MfaEnrolmentView;
  count: number;
}

function textOf(value: FormDataEntryValue | null): string {
  return typeof value === "string" ? value : "";
}

/** The QR code as an image source: GoTrue sends an SVG, as text or as a data URL. */
function qrSource(svg: string): string {
  if (svg.startsWith("data:")) return svg;
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`;
}

/**
 * Two-step verification: why it is needed (the roles that ask for it), then the provider's
 * way of doing it. With the fake adapter one confirm button asserts the factor, and the page
 * says so. With an authenticator app, a person without a factor enrols one (a QR code, the
 * secret as text, then a code), one with a factor answers a challenge with a code, and a
 * signed-in person with a verified factor sees it listed and may remove it with a fresh code.
 */
export function MfaView({
  mode,
  who,
  required,
  verified,
  requiringRoles,
  factors,
  verify,
  enrol,
  remove,
  fields,
  next,
  signInHref,
  accountHref,
  codeLength,
}: MfaViewProps) {
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => {
      const intent = textOf(formData.get("intent"));
      const action = intent === "enrol" ? enrol : intent === "remove" ? remove : verify;
      const state = await action(previous.state, formData);
      const enrolment =
        state.status === "ok"
          ? state.value?.enrolment
          : intent === "verify"
            ? previous.enrolment
            : undefined;
      return {
        state,
        ...(enrolment === undefined ? {} : { enrolment }),
        count: previous.count + 1,
      };
    },
    { state: idleAction<MfaActionView>(), count: 0 },
  );
  const { state, enrolment } = attempt;
  const errorsRef = useRef<HTMLDivElement>(null);
  const id = useId();
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const verifiedFactor = factors.find((factor) => factor.status === "verified");

  useEffect(() => {
    if (attempt.count > 0 && attempt.state.status === "error") errorsRef.current?.focus();
  }, [attempt]);

  const hidden = <>{next ? <input type="hidden" name={fields.next} value={next} /> : null}</>;

  let body: React.ReactNode;
  if (who === "anonymous") {
    body = (
      <Banner
        tone="info"
        action={
          <Button asChild size="sm">
            <Link href={signInHref as Route}>{t("common.signIn")}</Link>
          </Button>
        }
      >
        {t("mfa.signInFirst")}
      </Banner>
    );
  } else if (mode === "confirm") {
    body = (
      <form action={formAction} className="flex flex-col gap-4" data-slot="mfa-confirm">
        {hidden}
        <input type="hidden" name="intent" value="verify" />
        <Banner tone="warning" title={t("mfa.devTitle")}>
          {t("mfa.devBody")}
        </Banner>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("mfa.confirming") : t("mfa.confirm")}
          </Button>
        </div>
      </form>
    );
  } else if (enrolment !== undefined) {
    body = (
      <form action={formAction} className="flex flex-col gap-4" data-slot="mfa-enrol-verify">
        {hidden}
        <input type="hidden" name="intent" value="verify" />
        <input type="hidden" name={fields.factorId} value={enrolment.factorId} />
        <p className="text-sm text-fg-muted">{t("mfa.scanBody")}</p>
        {enrolment.qrSvg ? (
          // eslint-disable-next-line @next/next/no-img-element -- a data URL from the provider
          <img src={qrSource(enrolment.qrSvg)} alt={t("mfa.qrAlt")} width={200} height={200} />
        ) : null}
        <p className="text-sm">
          {t("mfa.secretLabel")}{" "}
          <code className="font-mono text-sm" data-slot="mfa-secret">
            {enrolment.secret}
          </code>
        </p>
        <CodeField id={id} state={state} fields={fields} codeLength={codeLength} />
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("mfa.verifying") : t("mfa.verify")}
          </Button>
        </div>
      </form>
    );
  } else if (factors.length === 0) {
    body = (
      <form action={formAction} className="flex flex-col gap-4" data-slot="mfa-enrol">
        {hidden}
        <input type="hidden" name="intent" value="enrol" />
        <p className="text-sm text-fg-muted">{t("mfa.enrolBody")}</p>
        <Field id={`${id}-name`} label={t("mfa.factorName")} description={t("mfa.factorNameHelp")}>
          <Input name={fields.friendlyName} maxLength={80} />
        </Field>
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("mfa.enrolling") : t("mfa.enrol")}
          </Button>
        </div>
      </form>
    );
  } else if (!verified || who === "pending") {
    body = (
      <form action={formAction} className="flex flex-col gap-4" data-slot="mfa-challenge">
        {hidden}
        <input type="hidden" name="intent" value="verify" />
        <input type="hidden" name={fields.factorId} value={(verifiedFactor ?? factors[0])?.id} />
        <p className="text-sm text-fg-muted">{t("mfa.challengeBody")}</p>
        <CodeField id={id} state={state} fields={fields} codeLength={codeLength} />
        <div>
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            {pending ? t("mfa.verifying") : t("mfa.verify")}
          </Button>
        </div>
      </form>
    );
  } else {
    body = (
      <div className="flex flex-col gap-4" data-slot="mfa-managed">
        <Banner tone="success">{t("mfa.managedBody")}</Banner>
        <ul className="flex flex-col gap-3">
          {factors.map((factor) => (
            <li
              key={factor.id}
              className="rounded-md border border-line p-3"
              data-factor={factor.id}
            >
              <form action={formAction} className="flex flex-col gap-3">
                {hidden}
                <input type="hidden" name="intent" value="remove" />
                <input type="hidden" name={fields.factorId} value={factor.id} />
                <p className="text-sm font-medium text-fg">
                  {factor.friendlyName || t("mfa.defaultFactorName")}
                </p>
                <CodeField
                  id={`${id}-${factor.id}`}
                  state={state}
                  fields={fields}
                  codeLength={codeLength}
                />
                <div>
                  <Button
                    type="submit"
                    variant="secondary"
                    disabled={pending}
                    aria-busy={pending || undefined}
                  >
                    {t("mfa.remove")}
                  </Button>
                </div>
              </form>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div data-slot="mfa" data-mode={mode} className="flex max-w-xl flex-col gap-6">
      <PageHeader
        title={t("mfa.title")}
        description={
          required
            ? t("mfa.requiredBy", { roles: requiringRoles.join(", ") })
            : t("mfa.optionalIntro")
        }
      />
      {verified && who === "session" ? (
        <p className="text-sm text-fg-muted" data-slot="mfa-status">
          {t("mfa.verifiedNote")}
        </p>
      ) : null}
      {state.status === "error" ? (
        <div
          ref={errorsRef}
          tabIndex={-1}
          data-slot="mfa-errors"
          className="flex flex-col gap-3 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus/50"
        >
          {problem ? (
            <ErrorState
              title={problem.title}
              detail={problem.detail}
              correlationId={problem.correlationId || undefined}
            />
          ) : null}
          {formErrors.length > 0 ? (
            <Banner tone="danger" title={t("mfa.refused")}>
              <ul>
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
          {!problem && formErrors.length === 0 ? (
            <Banner tone="danger" title={t("mfa.refused")}>
              {t("signIn.checkFields")}
            </Banner>
          ) : null}
        </div>
      ) : null}
      {body}
      {who === "session" ? (
        <p className="text-sm text-fg-muted">
          <Link href={accountHref as Route} className="underline hover:text-fg">
            {t("mfa.backToAccount")}
          </Link>
        </p>
      ) : null}
    </div>
  );
}

function CodeField({
  id,
  state,
  fields,
  codeLength,
}: {
  id: string;
  state: ActionState<MfaActionView>;
  fields: MfaFields;
  codeLength: number;
}) {
  return (
    <Field
      id={`${id}-code`}
      label={t("mfa.code")}
      description={t("signIn.codeHelp", { length: codeLength })}
      error={fieldErrorOf(state, fields.code)}
      required
    >
      <Input
        name={fields.code}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        maxLength={codeLength}
        className="max-w-40 font-mono text-lg tracking-widest"
      />
    </Field>
  );
}
