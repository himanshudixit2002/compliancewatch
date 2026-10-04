"use server";

import { redirect } from "next/navigation";
import type { BusinessLink, Recipient } from "@/entities/notification/types";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { toActionState } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { actionFailure, fieldFailure, type ActionState } from "@/shared/lib/action-state";
import { isUuid } from "@/shared/lib/identifiers";
import { DEFAULT_LANGUAGE } from "@/shared/lib/languages";
import { withQuery } from "@/shared/lib/url";
import { recipientsGateway } from "./gateway";
import { BUSINESS_CHOICES } from "./model/page";
import { RECIPIENT_FIELDS, parseRecipientForm } from "./model/recipient-form";
import { rolesFor } from "./model/recipients";

/**
 * The recipients page's server actions; each runs the screen's gate again (the proxy never sees
 * an action). Saving registers the recipient, or replaces it whole when it exists: the form's
 * choices plus what the form does not show (the user id, and the label of each business link it
 * keeps), with a new link named after the business. Removing deletes the recipient with its
 * addresses and links; the opt-ins stay with each address. Both return to the page on the
 * business it showed, saying what happened.
 */
const SCREEN_ID = "owner.settings.notification-recipients";

function pageHref(): string {
  return hrefFor(screenById(SCREEN_ID));
}

export async function saveRecipient(_state: ActionState, formData: FormData): Promise<ActionState> {
  const session = await requireScreenSession(screenById(SCREEN_ID));
  const gateway = recipientsGateway({ session });
  const recipientId = formData.get(RECIPIENT_FIELDS.recipientId);
  if (typeof recipientId !== "string" || !isUuid(recipientId.trim())) {
    return actionFailure(t("recipients.error.stale"));
  }
  const [businesses, templates, current] = await Promise.all([
    gateway.businesses(BUSINESS_CHOICES),
    gateway.templates(),
    gateway.get(recipientId.trim().toLowerCase()),
  ]);
  if (!businesses.ok) return toActionState(businesses);
  if (!templates.ok) return toActionState(templates);
  if (!current.ok && current.error.kind !== "not_found") return toActionState(current);
  const existing: Recipient | null = current.ok ? current.value : null;

  const names = new Map(businesses.value.items.map((business) => [business.id, business.name]));
  const roles = [...rolesFor(session.tenantKind)];
  if (existing !== null && !roles.includes(existing.role)) roles.push(existing.role);
  const parsed = parseRecipientForm(formData, {
    roles,
    languages: [
      DEFAULT_LANGUAGE,
      ...templates.value.map((template) => template.language),
      ...(existing === null ? [] : [existing.language]),
    ],
    businessIds: [...names.keys(), ...(existing?.businesses.map((link) => link.businessId) ?? [])],
  });
  if (!parsed.ok) {
    return parsed.fieldErrors === undefined
      ? actionFailure(parsed.formErrors ?? [])
      : fieldFailure(parsed.fieldErrors);
  }
  const form = parsed.value;
  const links: BusinessLink[] = form.businessIds.map((businessId) => {
    const kept = existing?.businesses.find((link) => link.businessId === businessId);
    return { businessId, label: kept?.label ?? (names.get(businessId) ?? "").trim() };
  });
  const saved = await gateway.put(form.recipientId, {
    role: form.role,
    userId: existing?.userId ?? null,
    language: form.language,
    digestMode: form.digestMode,
    orgLabel: form.orgLabel,
    addresses: form.addresses,
    businesses: links,
  });
  if (!saved.ok) return toActionState(saved);
  afterMutation({ paths: [pageHref()] });
  redirect(
    withQuery(pageHref(), {
      business: form.returnBusiness ?? links[0]?.businessId,
      saved: saved.value.id,
    }),
  );
}

export async function removeRecipient(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const session = await requireScreenSession(screenById(SCREEN_ID));
  const recipientId = formData.get(RECIPIENT_FIELDS.recipientId);
  if (typeof recipientId !== "string" || !isUuid(recipientId.trim())) {
    return actionFailure(t("recipients.error.stale"));
  }
  const removed = await recipientsGateway({ session }).remove(recipientId.trim().toLowerCase());
  // Already gone (removed in another tab) is the state the person asked for.
  if (!removed.ok && removed.error.kind !== "not_found") return toActionState(removed);
  const business = formData.get(RECIPIENT_FIELDS.returnBusiness);
  afterMutation({ paths: [pageHref()] });
  redirect(
    withQuery(pageHref(), {
      business: typeof business === "string" && isUuid(business) ? business : undefined,
      removed: "1",
    }),
  );
}
