import "server-only";

import { trace, type Attributes } from "@opentelemetry/api";
import type { ValueState } from "@/entities/business/types";
import { isGrantedAt } from "@/entities/consent/mappers";
import type { ConsentPurpose } from "@/entities/consent/types";
import type { LegalDocName } from "@/shared/config/legal-docs";
import type { FetchImpl } from "./api/client";
import type { ClientPrincipal } from "./api/services";
import { isEnabled } from "./flags";
import { readLegalVersions, type LegalVersion } from "./legal";
import { readConsentSummary } from "./required-consents";

/**
 * Product analytics: what a person did in the app, as one JSON line on stdout and an event on
 * the active OpenTelemetry span, for the onboarding funnel and the settings changes. Nothing is
 * sent to a third party.
 *
 * An event is emitted only when both hold, checked in this order on every call:
 *
 * 1. the `web.analytics_enabled` flag is on for the tenant (off by default; server/flags.ts);
 * 2. the person's analytics consent is current: the latest analytics record from
 *    `GET /v1/identity/consents?subject=<user id>`, read on every event, grants it with the
 *    privacy notice's version this build ships. A withdrawal therefore stops the next event,
 *    and a new privacy notice stops them until the person agrees again. (The session claim
 *    `analyticsConsent` is not read: nothing refreshes it when a person withdraws.)
 *
 * With the flag off nothing is read, so the check costs nothing where analytics is not in use;
 * with it on, each event costs one consent read.
 * The events are a closed list: every property is a count, a flag, or a value from a fixed
 * list (a step, a purpose, an attribute key, a channel, a plan key), never text a person typed,
 * an answer's value, a GSTIN, a number or an address. `track` never throws and never fails the
 * request it runs in: a failure is logged as one warning line and the event is dropped.
 */
export type OnboardingStep =
  | { step: "consent" }
  | { step: "business"; created: boolean; looked_up: boolean }
  | { step: "question"; attribute: string; state: ValueState };

export type ProductEvent =
  | { name: "onboarding_step_completed"; properties: OnboardingStep }
  | {
      name: "onboarding_summary_viewed";
      properties: {
        complete: boolean;
        answered: number;
        total: number;
        unsure: number;
        open_review_tasks: number;
      };
    }
  | {
      name: "consent_changed";
      properties: { purpose: ConsentPurpose; change: "give" | "withdraw" };
    }
  | {
      name: "notification_preference_saved";
      properties: { channel: "whatsapp" | "email"; opted_in: boolean };
    }
  | { name: "subscription_started"; properties: { plan_key: string } };

export type ProductEventName = ProductEvent["name"];

/** Who did it: the session's user and tenant. */
export type AnalyticsPrincipal = ClientPrincipal;

export interface TrackDeps {
  fetchImpl?: FetchImpl;
  /** The documents' Version lines; read from docs/legal by default. */
  versions?: Readonly<Record<LegalDocName, LegalVersion>>;
  /** Where the event line goes; stdout by default. */
  write?: (line: string) => void;
  /** Where a failure is logged; stderr by default. */
  warn?: (line: string) => void;
  now?: () => Date;
}

/** Why an event was or was not emitted, for tests and for the caller's own logging. */
export type TrackOutcome = "sent" | "flag_off" | "no_consent" | "failed";

export const ANALYTICS_FLAG = "web.analytics_enabled";

/** The purpose the analytics consent is recorded under. */
export const ANALYTICS_PURPOSE: ConsentPurpose = "analytics";

/**
 * The notice version a current analytics grant carries: the privacy notice at the Version this
 * build ships, in the `<document>@<Version line>` form the consent records use (D-026).
 * `features/consents` maps the analytics purpose to the same document; its test holds the two
 * together.
 */
export function analyticsNoticeVersion(
  versions: Readonly<Record<LegalDocName, LegalVersion>>,
): string {
  return `privacy-notice@${versions["privacy-notice"].version}`;
}

async function consentGranted(principal: AnalyticsPrincipal, deps: TrackDeps): Promise<boolean> {
  const summary = await readConsentSummary(principal, deps.fetchImpl);
  if (!summary.ok) return false;
  const notice = analyticsNoticeVersion(deps.versions ?? readLegalVersions());
  return isGrantedAt(summary.value, ANALYTICS_PURPOSE, notice);
}

/** The event's properties as span attributes, each under `product.`. */
export function spanAttributes(event: ProductEvent, principal: AnalyticsPrincipal): Attributes {
  const attributes: Attributes = { "product.tenant_id": principal.tenantId };
  for (const [key, value] of Object.entries(event.properties)) {
    attributes[`product.${key}`] = value as string | number | boolean;
  }
  return attributes;
}

/** The JSON line for one event. */
export function eventLine(event: ProductEvent, principal: AnalyticsPrincipal, at: Date): string {
  return JSON.stringify({
    level: "info",
    event: "product_event",
    name: event.name,
    at: at.toISOString(),
    tenant_id: principal.tenantId,
    user_id: principal.userId,
    properties: event.properties,
  });
}

/** Emits the event when the flag is on and the person gave the analytics consent. */
export async function track(
  principal: AnalyticsPrincipal,
  event: ProductEvent,
  deps: TrackDeps = {},
): Promise<TrackOutcome> {
  try {
    if (!(await isEnabled(ANALYTICS_FLAG, { tenantId: principal.tenantId }))) return "flag_off";
    if (!(await consentGranted(principal, deps))) return "no_consent";
    const at = (deps.now ?? (() => new Date()))();
    (deps.write ?? console.log)(eventLine(event, principal, at));
    trace.getActiveSpan()?.addEvent(`product.${event.name}`, spanAttributes(event, principal), at);
    return "sent";
  } catch (error) {
    (deps.warn ?? console.warn)(
      JSON.stringify({
        level: "warn",
        event: "product_event_failed",
        name: event.name,
        error: error instanceof Error ? error.message : String(error),
      }),
    );
    return "failed";
  }
}
