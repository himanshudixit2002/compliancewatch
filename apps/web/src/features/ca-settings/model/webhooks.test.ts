import { describe, expect, it } from "vitest";
import { isMessageKey, t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import {
  DELIVERY_TONE,
  WEBHOOK_EVENTS,
  WEBHOOK_EVENT_LABEL,
  WEBHOOK_STATUS_LABEL,
  WEBHOOK_STATUS_TONE,
  deliveryOutcome,
  deliveryText,
  webhookCounts,
} from "./webhooks";
import type { Webhook, WebhookStatus } from "./webhooks";

const AT = "2026-10-02T04:30:00Z";

function webhook(id: string, status: WebhookStatus): Webhook {
  return {
    id,
    url: `https://erp.example.com/hooks/${id}`,
    events: ["rule.published"],
    status,
    createdAt: "2026-07-01T05:00:00Z",
    lastDelivery: null,
  };
}

describe("labels and tones", () => {
  it("words every event and status", () => {
    expect(WEBHOOK_EVENTS.map((event) => t(WEBHOOK_EVENT_LABEL[event]))).toEqual([
      "A rule is published",
      "A rule is replaced by a newer version",
      "An obligation is created",
      "An obligation is due soon",
      "An obligation is closed",
    ]);
    const statuses: WebhookStatus[] = ["active", "paused"];
    for (const status of statuses) expect(isMessageKey(WEBHOOK_STATUS_LABEL[status])).toBe(true);
    expect(statuses.map((status) => WEBHOOK_STATUS_TONE[status])).toEqual(["success", "warning"]);
    expect(DELIVERY_TONE).toEqual({ none: "neutral", delivered: "success", failed: "danger" });
  });
});

describe("deliveryOutcome", () => {
  it("is none before the first delivery", () => {
    expect(deliveryOutcome(null)).toBe("none");
  });

  it("counts only a 2xx answer as delivered", () => {
    const outcome = (statusCode: number | null) => deliveryOutcome({ at: AT, statusCode });
    expect([200, 204, 299].map(outcome)).toEqual(["delivered", "delivered", "delivered"]);
    expect([199, 301, 404, 500, null].map(outcome)).toEqual([
      "failed",
      "failed",
      "failed",
      "failed",
      "failed",
    ]);
  });
});

describe("deliveryText", () => {
  it("says when the latest delivery was attempted and what the endpoint answered", () => {
    const when = formatDateTime(AT);
    expect(deliveryText(null)).toBe("Nothing sent yet");
    expect(deliveryText({ at: AT, statusCode: 200 })).toBe(`Delivered ${when}: HTTP 200`);
    expect(deliveryText({ at: AT, statusCode: 503 })).toBe(`Failed ${when}: HTTP 503`);
    expect(deliveryText({ at: AT, statusCode: null })).toBe(`Failed ${when}: no answer`);
  });
});

describe("webhookCounts", () => {
  it("counts the endpoints and the paused ones", () => {
    expect(
      webhookCounts([webhook("a", "active"), webhook("b", "paused"), webhook("c", "paused")]),
    ).toEqual({ total: 3, paused: 2 });
    expect(webhookCounts([])).toEqual({ total: 0, paused: 0 });
  });
});
