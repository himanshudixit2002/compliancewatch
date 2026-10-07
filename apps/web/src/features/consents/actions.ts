"use server";

import { redirect } from "next/navigation";
import type { ConsentPurpose } from "@/entities/consent/types";
import { track } from "@/server/analytics";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { onboardingGate, readLegalVersions } from "@/server/legal";
import { rememberRecipient } from "@/server/remembered-recipients";
import { toActionState, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { formatDateTime } from "@/shared/lib/dates";
import { consentsGateway } from "./gateway";
import { consentChangeRecord, parseConsentChange, type ConsentChangeChoice } from "./model/change";
import { grantedPurposes, purposesToRecord } from "./model/consent-step";
import { parseConsentForm, whatsappRecipient } from "./model/form";
import { checkboxLabel, noticeFor, purposeLabel } from "./model/purposes";
import type { ConsentChange } from "./model/settings";

/**
 * The consent step's server action. It runs the screen's gate again (the proxy never sees an
 * action), reads the user's current records, checks the form's shape (a required purpose
 * already granted at the current version has no box and needs none), and appends one record
 * per ticked purpose not already granted at the current notice version, in the order they are
 * asked: subject and recorded_by are the user id, the source is web_onboarding, the notice
 * version is `<document>@<Version line>`, and the evidence is the checkbox sentence as shown.
 * With the WhatsApp box ticked it then opts the number in on the notification service (keyed,
 * like the bot's opt-ins, by the digits without the plus) and remembers the number on this
 * device for the settings pages (server/remembered-recipients.ts). Only when everything is
 * recorded does it move on to the business step. It never withdraws: a purpose already granted
 * is shown as agreed rather than as a box, so leaving it alone cannot read as a choice to stop;
 * withdrawing is `changeConsent`'s job on the settings page.
 *
 * Records are append-only and each POST stands alone, so a failure part-way leaves the earlier
 * records in place; the form then says which were recorded, and submitting again records only
 * the rest. In production, while the terms or the privacy notice is a draft, the step is closed
 * (server/legal.ts, onboardingGate) and the action records nothing.
 */
function failedAfter(result: Result<unknown>, recorded: readonly ConsentPurpose[]): ActionState {
  const state = toActionState<undefined>(result as Result<undefined>);
  if (state.status !== "error") return state;
  const summary =
    recorded.length === 0
      ? t("consent.partialNone")
      : t("consent.partial", { purposes: recorded.map(purposeLabel).join(", ") });
  return { ...state, formErrors: [summary] };
}

export async function recordConsents(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const screen = screenById("owner.onboarding");
  const session = await requireScreenSession(screen);
  const versions = readLegalVersions();
  if (onboardingGate({ versions }).closed) return actionFailure(t("onboardingClosed.refused"));

  const gateway = consentsGateway({ session });
  const summary = await gateway.summary(session.userId);
  if (!summary.ok) return failedAfter(summary, []);
  const parsed = parseConsentForm(formData, {
    offerWhatsapp: session.tenantKind === "business",
    granted: grantedPurposes(summary.value, versions),
  });
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);

  const recorded: ConsentPurpose[] = [];
  for (const purpose of purposesToRecord(parsed.value.purposes, summary.value, versions)) {
    const result = await gateway.record({
      subject: session.userId,
      purpose,
      granted: true,
      source: "web_onboarding",
      noticeVersion: noticeFor(purpose, versions),
      evidence: checkboxLabel(purpose),
      recordedBy: session.userId,
    });
    if (!result.ok) return failedAfter(result, recorded);
    recorded.push(purpose);
  }

  const { whatsappNumber } = parsed.value;
  if (whatsappNumber !== null) {
    const recipient = whatsappRecipient(whatsappNumber);
    const preference = await gateway.setPreference("whatsapp", recipient, {
      optedIn: true,
      source: "web_onboarding",
      subject: session.userId,
    });
    if (!preference.ok) {
      const state = toActionState<undefined>(preference);
      return state.status === "error"
        ? { ...state, formErrors: [t("consent.preferenceFailed")] }
        : state;
    }
    await rememberRecipient(session.userId, "whatsapp", recipient);
  }

  await track(session, { name: "onboarding_step_completed", properties: { step: "consent" } });
  afterMutation({ paths: [hrefFor(screen)] });
  redirect(hrefFor(screenById("owner.onboarding.business")));
}

/** What a change on the settings page did, for the row's status line. */
export interface ConsentChangeResult {
  purpose: ConsentPurpose;
  change: ConsentChange;
  /** False when the change was already the current state and nothing new was recorded. */
  recorded: boolean;
  /** The number opted in or out, "+91..."; null when no number was involved. */
  number: string | null;
}

function changeFailed(result: Result<unknown>, message: string): ActionState<ConsentChangeResult> {
  const state = toActionState<undefined>(result as Result<undefined>);
  return state.status === "error" ? { ...state, formErrors: [message] } : { status: "idle" };
}

function changeMessage(
  choice: ConsentChangeChoice,
  recordedAt: string | null,
  number: string | null,
): string {
  const purpose = purposeLabel(choice.purpose);
  const parts: string[] = [];
  if (recordedAt === null) {
    parts.push(
      choice.change === "withdraw"
        ? t("consentSettings.done.alreadyWithdrawn", { purpose })
        : t("consentSettings.done.alreadyGiven", { purpose }),
    );
  } else {
    parts.push(
      choice.change === "withdraw"
        ? t("consentSettings.done.withdrawn", { purpose, date: recordedAt })
        : t("consentSettings.done.given", { purpose, date: recordedAt }),
    );
  }
  if (number !== null) {
    parts.push(
      choice.change === "withdraw"
        ? t("consentSettings.done.optedOut", { number })
        : t("consentSettings.done.optedIn", { number }),
    );
  } else if (choice.purpose === "whatsapp_reminders" && choice.change === "withdraw") {
    parts.push(t("consentSettings.done.noNumber"));
  }
  return parts.join(" ");
}

/**
 * The consents settings page's server action: gives or withdraws one optional purpose. It runs
 * the screen's gate again, checks the form's shape, reads the user's records, and adds one
 * record (subject and recorded_by the user id, source web_settings, and the confirmed sentence
 * inside the evidence), or none when the change is
 * already the current state.
 *
 * WhatsApp reminders also move the number. A withdrawal opts the number out first, so reminders
 * stop even when the record then fails (the answer says so, and trying again records it); with
 * no number it records the withdrawal alone. Giving records the consent first and then opts the
 * number in, as the consent step does. A number used either way is remembered on this device.
 * While onboarding is closed (production with a required document still a draft) a consent can
 * be withdrawn but not given.
 */
export async function changeConsent(
  _state: ActionState<ConsentChangeResult>,
  formData: FormData,
): Promise<ActionState<ConsentChangeResult>> {
  const screen = screenById("owner.settings.consents");
  const session = await requireScreenSession(screen);
  const parsed = parseConsentChange(formData, {
    offerWhatsapp: session.tenantKind === "business",
  });
  if (!parsed.ok) {
    return {
      status: "error",
      ...(parsed.fieldErrors === undefined ? {} : { fieldErrors: parsed.fieldErrors }),
      ...(parsed.formErrors === undefined ? {} : { formErrors: parsed.formErrors }),
    };
  }
  const choice = parsed.value;
  const versions = readLegalVersions();
  if (choice.change === "give" && onboardingGate({ versions }).closed) {
    return actionFailure(t("consentSettings.error.closed"));
  }
  const gateway = consentsGateway({ session });
  const summary = await gateway.summary(session.userId);
  if (!summary.ok) return changeFailed(summary, t("consentSettings.refused"));

  const recipient =
    choice.whatsappNumber === null ? null : whatsappRecipient(choice.whatsappNumber);
  if (recipient !== null && choice.change === "withdraw") {
    const optOut = await gateway.setPreference("whatsapp", recipient, {
      optedIn: false,
      source: "web_settings",
      subject: session.userId,
    });
    if (!optOut.ok) return changeFailed(optOut, t("consentSettings.error.optOutFailed"));
    await rememberRecipient(session.userId, "whatsapp", recipient);
  }

  const record = consentChangeRecord(choice, summary.value, versions, session.userId);
  let recordedAt: string | null = null;
  if (record !== null) {
    const written = await gateway.record(record);
    if (!written.ok) {
      return changeFailed(
        written,
        recipient !== null && choice.change === "withdraw"
          ? t("consentSettings.error.recordAfterOptOut")
          : t("consentSettings.refused"),
      );
    }
    recordedAt = formatDateTime(written.value.recordedAt);
    await track(session, {
      name: "consent_changed",
      properties: { purpose: choice.purpose, change: choice.change },
    });
  }

  if (recipient !== null && choice.change === "give") {
    const optIn = await gateway.setPreference("whatsapp", recipient, {
      optedIn: true,
      source: "web_settings",
      subject: session.userId,
    });
    if (!optIn.ok) return changeFailed(optIn, t("consentSettings.error.optInFailed"));
    await rememberRecipient(session.userId, "whatsapp", recipient);
  }

  afterMutation({
    paths: [hrefFor(screen), hrefFor(screenById("owner.settings.notifications"))],
  });
  return actionSuccess(
    {
      purpose: choice.purpose,
      change: choice.change,
      recorded: record !== null,
      number: choice.whatsappNumber,
    },
    changeMessage(choice, recordedAt, choice.whatsappNumber),
  );
}
