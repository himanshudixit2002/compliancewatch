"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useEffect, useId, useRef, useState } from "react";
import { Banner, Button, ErrorState, Field, Input, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

/** The step the phone and email forms are on (the actions' SignInView, structurally). */
export interface SignInStepView {
  step: "phone" | "code" | "email";
  phone?: string;
}

export type SignInStepAction = (
  state: ActionState<SignInStepView>,
  formData: FormData,
) => Promise<ActionState<SignInStepView>>;

export interface SignInFormFields {
  phone: string;
  code: string;
  email: string;
  next: string;
}

export interface MethodLink {
  method: "dev" | "phone" | "email";
  href: string;
  label: string;
}

export interface SignInFormProps {
  method: "phone" | "email";
  startPhone: SignInStepAction;
  verifyCode: SignInStepAction;
  sendEmail: SignInStepAction;
  fields: SignInFormFields;
  /** The same-origin path to return to after signing in. */
  next?: string;
  /** What the page says above the form (a session that ended, an expired link). */
  notice?: string;
  /** The other methods the provider offers, as links the page builds. */
  otherMethods: readonly MethodLink[];
  /** The fake provider: a note that any code passes. */
  devNotice?: boolean;
  resendAfterSeconds: number;
  codeLength: number;
}

interface Attempt {
  state: ActionState<SignInStepView>;
  /** The step shown: the action's answer, or the step the refused submit was on. */
  step: SignInStepView["step"];
  phone: string;
  /** When the last code was sent (epoch ms), for the wait before another; 0 for none. */
  sentAt: number;
  count: number;
}

function textOf(value: FormDataEntryValue | null): string {
  return typeof value === "string" ? value : "";
}

/** The seconds left of a wait that began at `since` (epoch ms; 0 for none), ticking once a second. */
function useCountdown(seconds: number, since: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (since === 0) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [since]);
  if (since === 0) return 0;
  const elapsed = Math.max(0, Math.floor((now - since) / 1000));
  return Math.max(0, seconds - elapsed);
}

/**
 * The real sign-in: a phone number, then the six-digit code sent to it (with another code on
 * offer after a short wait and a way back to the number), or an email address for a link. The
 * server actions say which step comes next; a refused submit keeps what was typed, shows the
 * provider's or identity's words and moves focus to them.
 */
export function SignInForm({
  method,
  startPhone,
  verifyCode,
  sendEmail,
  fields,
  next,
  notice,
  otherMethods,
  devNotice = false,
  resendAfterSeconds,
  codeLength,
}: SignInFormProps) {
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => {
      const intent = textOf(formData.get("intent"));
      const action = intent === "verify" ? verifyCode : intent === "email" ? sendEmail : startPhone;
      const state = await action(previous.state, formData);
      const submitted = intent === "verify" ? "code" : intent === "email" ? "email" : "phone";
      const step =
        state.status === "ok" && state.value !== undefined ? state.value.step : submitted;
      const codeSent = state.status === "ok" && step === "code";
      return {
        state,
        step,
        phone: textOf(formData.get(fields.phone)) || previous.phone,
        sentAt: codeSent ? Date.now() : previous.sentAt,
        count: previous.count + 1,
      };
    },
    { state: idleAction<SignInStepView>(), step: method, phone: "", sentAt: 0, count: 0 },
  );
  const { state, step } = attempt;
  const phone = state.status === "ok" && state.value?.phone ? state.value.phone : attempt.phone;
  const errorsRef = useRef<HTMLDivElement>(null);
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  const hasFieldErrors = state.status === "error" && state.fieldErrors !== undefined;
  const id = useId();
  const resendIn = useCountdown(resendAfterSeconds, attempt.sentAt);

  useEffect(() => {
    if (attempt.count > 0 && attempt.state.status === "error") errorsRef.current?.focus();
  }, [attempt]);

  return (
    <div data-slot="sign-in" data-step={step} className="flex max-w-md flex-col gap-6">
      <PageHeader
        title={t("signIn.title")}
        description={step === "email" ? t("signIn.emailIntro") : t("signIn.phoneIntro")}
      />
      {notice ? <Banner tone="info">{notice}</Banner> : null}
      {devNotice ? <Banner tone="info">{t("signIn.devAnyCode")}</Banner> : null}
      {state.status === "error" ? (
        <div
          ref={errorsRef}
          tabIndex={-1}
          data-slot="sign-in-errors"
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
            <Banner tone="danger" title={t("signIn.refused")}>
              <ul>
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
          {!problem && formErrors.length === 0 && hasFieldErrors ? (
            <Banner tone="danger" title={t("signIn.refused")}>
              {t("signIn.checkFields")}
            </Banner>
          ) : null}
        </div>
      ) : null}
      <form action={formAction} className="flex flex-col gap-5" data-slot="sign-in-form">
        {next ? <input type="hidden" name={fields.next} value={next} /> : null}
        {step === "phone" ? (
          <>
            <input type="hidden" name="intent" value="start" />
            <Field
              id={`${id}-phone`}
              label={t("signIn.phone")}
              description={t("signIn.phoneHelp")}
              error={fieldErrorOf(state, fields.phone)}
              required
            >
              <Input
                key={`phone-${attempt.count}`}
                name={fields.phone}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                defaultValue={attempt.phone}
              />
            </Field>
            <div>
              <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
                {pending ? t("signIn.sendingCode") : t("signIn.sendCode")}
              </Button>
            </div>
          </>
        ) : null}
        {step === "code" ? (
          <>
            <input type="hidden" name="intent" value="verify" />
            <input type="hidden" name={fields.phone} value={phone} />
            <p className="text-sm text-fg-muted" data-slot="code-sent-to">
              {t("signIn.codeSentTo", { phone })}
            </p>
            <Field
              id={`${id}-code`}
              label={t("signIn.code")}
              description={t("signIn.codeHelp", { length: codeLength })}
              error={fieldErrorOf(state, fields.code)}
              required
            >
              <Input
                key={`code-${attempt.count}`}
                name={fields.code}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={codeLength}
                className="max-w-40 font-mono text-lg tracking-widest"
              />
            </Field>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
                {pending ? t("signIn.verifying") : t("signIn.verify")}
              </Button>
              <Button
                type="submit"
                variant="secondary"
                name="intent"
                value="start"
                formNoValidate
                disabled={pending || resendIn > 0}
                data-slot="resend"
              >
                {resendIn > 0 ? t("signIn.resendIn", { seconds: resendIn }) : t("signIn.resend")}
              </Button>
            </div>
          </>
        ) : null}
        {step === "email" ? (
          <>
            <input type="hidden" name="intent" value="email" />
            <Field
              id={`${id}-email`}
              label={t("signIn.email")}
              description={t("signIn.emailHelp")}
              error={fieldErrorOf(state, fields.email)}
              required
            >
              <Input
                key={`email-${attempt.count}`}
                name={fields.email}
                type="email"
                inputMode="email"
                autoComplete="email"
              />
            </Field>
            <div>
              <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
                {pending ? t("signIn.sendingLink") : t("signIn.sendLink")}
              </Button>
            </div>
          </>
        ) : null}
      </form>
      {step === "code" ? (
        <form action={formAction} data-slot="change-number">
          <input type="hidden" name="intent" value="start" />
          <input type="hidden" name={fields.phone} value="" />
          <ChangeNumberNote otherMethods={otherMethods} />
        </form>
      ) : (
        <MethodLinks links={otherMethods} />
      )}
    </div>
  );
}

function ChangeNumberNote({ otherMethods }: { otherMethods: readonly MethodLink[] }) {
  const phoneLink = otherMethods.find((link) => link.method === "phone");
  return (
    <p className="text-sm text-fg-muted">
      <Link
        href={(phoneLink?.href ?? "/sign-in") as Route}
        className="underline hover:text-fg"
        data-slot="use-another-number"
      >
        {t("signIn.useAnotherNumber")}
      </Link>
    </p>
  );
}

export function MethodLinks({ links }: { links: readonly MethodLink[] }) {
  if (links.length === 0) return null;
  return (
    <nav aria-label={t("signIn.otherMethods")} data-slot="sign-in-methods">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {links.map((link) => (
          <li key={link.method}>
            <Link href={link.href as Route} className="underline hover:text-fg">
              {link.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
