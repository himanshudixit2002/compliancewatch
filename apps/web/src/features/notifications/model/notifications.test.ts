import { describe, expect, it } from "vitest";
import { t } from "@/shared/i18n";
import {
  DELIVERY_STATES,
  channelLabelKey,
  deliveryBucket,
  deliveryLabelKey,
  deliveryTone,
  notificationCounts,
} from "./notifications";
import type { DeliveryState, NotificationSummary } from "./notifications";

function summary(id: string, state: DeliveryState): NotificationSummary {
  return {
    id,
    subject: `Subject ${id}`,
    channel: "whatsapp",
    state,
    recipient: "+919876543210",
    templateKey: "reminder_due",
    sentAt: null,
  };
}

describe("delivery states", () => {
  it("gives every state a tone, a label and a bucket", () => {
    expect(DELIVERY_STATES.map(deliveryTone)).toEqual([
      "neutral",
      "neutral",
      "info",
      "success",
      "success",
      "danger",
      "warning",
    ]);
    expect(DELIVERY_STATES.map((state) => t(deliveryLabelKey(state)))).toEqual([
      "Queued",
      "Waiting for the digest",
      "Sent",
      "Delivered",
      "Read",
      "Failed",
      "Suppressed",
    ]);
    expect(DELIVERY_STATES.map(deliveryBucket)).toEqual([
      "pending",
      "pending",
      "pending",
      "delivered",
      "delivered",
      "failed",
      "failed",
    ]);
  });

  it("names both channels", () => {
    expect(t(channelLabelKey("whatsapp"))).toBe("WhatsApp");
    expect(t(channelLabelKey("email"))).toBe("Email");
  });
});

describe("notificationCounts", () => {
  it("is all zeros for no notifications", () => {
    expect(notificationCounts([])).toEqual({ total: 0, pending: 0, delivered: 0, failed: 0 });
  });

  it("counts each delivery bucket", () => {
    const items = DELIVERY_STATES.map((state, index) => summary(String(index), state));
    expect(notificationCounts(items)).toEqual({ total: 7, pending: 3, delivered: 2, failed: 2 });
  });
});
