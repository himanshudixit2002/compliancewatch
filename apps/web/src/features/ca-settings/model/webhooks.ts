import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";

/**
 * The webhooks screen's model: the endpoints a CA firm registered (`POST /v1/webhooks`, not
 * scheduled yet) to receive obligation and change events, with how the latest delivery went
 * (`GET /v1/webhooks/{webhook_id}/deliveries`). Deliveries are signed and retried for 24 hours;
 * an endpoint whose deliveries keep failing is paused.
 */
export const WEBHOOK_EVENTS = [
  "rule.published",
  "rule.superseded",
  "obligation.created",
  "obligation.due_soon",
  "obligation.closed",
] as const;

/** The domain events an endpoint can receive, named as the event contracts name them. */
export type WebhookEvent = (typeof WEBHOOK_EVENTS)[number];

export type WebhookStatus = "active" | "paused";

/** How the latest delivery went: none yet, a 2xx answer, or anything else. */
export type DeliveryOutcome = "none" | "delivered" | "failed";

export interface WebhookDelivery {
  /** When the delivery was attempted, an ISO instant. */
  at: string;
  /** The HTTP status the endpoint answered with; null when it did not answer. */
  statusCode: number | null;
}

export interface Webhook {
  id: string;
  /** The https address the events are posted to. */
  url: string;
  events: readonly WebhookEvent[];
  status: WebhookStatus;
  /** An ISO instant. */
  createdAt: string;
  /** The latest delivery attempt; null before the first. */
  lastDelivery: WebhookDelivery | null;
}

export interface WebhookCounts {
  total: number;
  paused: number;
}

/** The form fields the create, test and remove actions read. */
export const WEBHOOK_FIELDS = { url: "url", events: "events", webhookId: "webhook_id" } as const;

export const WEBHOOK_EVENT_LABEL: Readonly<Record<WebhookEvent, MessageKey>> = {
  "rule.published": "caSettings.webhooks.event.rulePublished",
  "rule.superseded": "caSettings.webhooks.event.ruleSuperseded",
  "obligation.created": "caSettings.webhooks.event.obligationCreated",
  "obligation.due_soon": "caSettings.webhooks.event.obligationDueSoon",
  "obligation.closed": "caSettings.webhooks.event.obligationClosed",
};

export const WEBHOOK_STATUS_LABEL: Readonly<Record<WebhookStatus, MessageKey>> = {
  active: "caSettings.webhooks.status.active",
  paused: "caSettings.webhooks.status.paused",
};

export const WEBHOOK_STATUS_TONE: Readonly<Record<WebhookStatus, Tone>> = {
  active: "success",
  paused: "warning",
};

export const DELIVERY_TONE: Readonly<Record<DeliveryOutcome, Tone>> = {
  none: "neutral",
  delivered: "success",
  failed: "danger",
};

export function deliveryOutcome(delivery: WebhookDelivery | null): DeliveryOutcome {
  if (delivery === null) return "none";
  const { statusCode } = delivery;
  return statusCode !== null && statusCode >= 200 && statusCode < 300 ? "delivered" : "failed";
}

/** The latest delivery in words: when it was attempted and what the endpoint answered. */
export function deliveryText(delivery: WebhookDelivery | null): string {
  if (delivery === null) return t("caSettings.webhooks.delivery.none");
  const when = formatDateTime(delivery.at);
  if (delivery.statusCode === null) return t("caSettings.webhooks.delivery.noAnswer", { when });
  const vars = { when, code: delivery.statusCode };
  return deliveryOutcome(delivery) === "delivered"
    ? t("caSettings.webhooks.delivery.delivered", vars)
    : t("caSettings.webhooks.delivery.failed", vars);
}

export function webhookCounts(webhooks: readonly Webhook[]): WebhookCounts {
  return {
    total: webhooks.length,
    paused: webhooks.filter((webhook) => webhook.status === "paused").length,
  };
}
