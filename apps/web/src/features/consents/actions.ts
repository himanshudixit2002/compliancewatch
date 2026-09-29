"use server";

import { redirect } from "next/navigation";
import type { ConsentPurpose } from "@/entities/consent/types";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { readLegalVersions } from "@/server/legal";
import { toActionState, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { fieldFailure, type ActionState } from "@/shared/lib/action-state";
import { consentsGateway } from "./gateway";
import { purposesToRecord } from "./model/consent-step";
import { parseConsentForm, whatsappRecipient } from "./model/form";
import { checkboxLabel, noticeFor, purposeLabel } from "./model/purposes";

/**
 * The consent step's server action. It runs the screen's gate again (the proxy never sees an
 * action), checks the form's shape, reads the user's current records, and appends one record
 * per ticked purpose not already granted at the current notice version, in the order they are
 * asked: subject and recorded_by are the user id, the source is web_onboarding, the notice
 * version is `<document>@<Version line>`, and the evidence is the checkbox sentence as shown.
 * With the WhatsApp box ticked it then opts the number in on the notification service (keyed,
 * like the bot's opt-ins, by the digits without the plus). Only
 * when everything is recorded does it move on to the business step.
 *
 * Records are append-only and each POST stands alone, so a failure part-way leaves the earlier
 * records in place; the form then says which were recorded, and submitting again records only
 * the rest.
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
  const parsed = parseConsentForm(formData, { offerWhatsapp: session.tenantKind === "business" });
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);

  const versions = readLegalVersions();
  const gateway = consentsGateway({ session });
  const summary = await gateway.summary(session.userId);
  if (!summary.ok) return failedAfter(summary, []);

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
    const preference = await gateway.setPreference("whatsapp", whatsappRecipient(whatsappNumber), {
      optedIn: true,
      source: "web_onboarding",
    });
    if (!preference.ok) {
      const state = toActionState<undefined>(preference);
      return state.status === "error"
        ? { ...state, formErrors: [t("consent.preferenceFailed")] }
        : state;
    }
  }

  afterMutation({ paths: [hrefFor(screen)] });
  redirect(hrefFor(screenById("owner.onboarding.business")));
}
