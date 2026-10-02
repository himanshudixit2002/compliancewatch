import { describe, expect, it } from "vitest";
import { t } from "@/shared/i18n";
import {
  activeDigestCount,
  channelLabelKey,
  connectedCount,
  digestModeKey,
  dispatchSummary,
  occasionLabelKey,
  stateBucket,
  stateLabelKey,
  stateTone,
} from "./admin-notifications";
import type {
  ChannelHealth,
  DeliveryState,
  DigestSchedule,
  DispatchEntry,
  OccasionKind,
} from "./admin-notifications";

const STATES: readonly DeliveryState[] = [
  "queued",
  "digest_pending",
  "sent",
  "delivered",
  "read",
  "failed",
  "suppressed",
];

function dispatch(id: string, state: DeliveryState): DispatchEntry {
  return {
    id,
    occasion: "reminder",
    channel: "whatsapp",
    recipient: "+919876543210",
    state,
    createdAt: "2026-10-01T05:00:00Z",
  };
}

describe("labels", () => {
  it("gives every delivery state a tone, a label and a bucket", () => {
    expect(STATES.map(stateTone)).toEqual([
      "neutral",
      "neutral",
      "info",
      "success",
      "success",
      "danger",
      "warning",
    ]);
    expect(STATES.map((state) => t(stateLabelKey(state)))).toEqual([
      "Queued",
      "Waiting for the digest",
      "Sent",
      "Delivered",
      "Read",
      "Failed",
      "Suppressed",
    ]);
    expect(STATES.map(stateBucket)).toEqual([
      "pending",
      "pending",
      "pending",
      "delivered",
      "delivered",
      "failed",
      "failed",
    ]);
  });

  it("names occasions, channels and digest modes", () => {
    const occasions: OccasionKind[] = [
      "change_card",
      "reminder",
      "closure",
      "reschedule",
      "manual",
    ];
    expect(occasions.map((occasion) => t(occasionLabelKey(occasion)))).toEqual([
      "Change card",
      "Reminder",
      "Closure",
      "Reschedule",
      "Manual send",
    ]);
    expect(t(channelLabelKey("whatsapp"))).toBe("WhatsApp");
    expect(t(channelLabelKey("email"))).toBe("Email");
    expect(t(digestModeKey("off"))).toBe("Off");
    expect(t(digestModeKey("daily"))).toBe("Daily");
  });
});

describe("dispatchSummary", () => {
  it("has no rate before any dispatch settles", () => {
    expect(dispatchSummary([])).toEqual({ total: 0, delivered: 0, failed: 0, deliveryRate: null });
    expect(dispatchSummary([dispatch("a", "queued")]).deliveryRate).toBeNull();
  });

  it("rates delivered against settled dispatches, rounded to a whole percent", () => {
    const entries = STATES.map((state, index) => dispatch(String(index), state));
    expect(dispatchSummary(entries)).toEqual({
      total: 7,
      delivered: 2,
      failed: 2,
      deliveryRate: 50,
    });
    expect(
      dispatchSummary([dispatch("a", "read"), dispatch("b", "read"), dispatch("c", "failed")])
        .deliveryRate,
    ).toBe(67);
  });
});

describe("counts", () => {
  it("counts connected channels and digests that are not off", () => {
    const channels: ChannelHealth[] = [
      { channel: "whatsapp", connected: true, sentToday: 1, dailyQuota: 10, lastSentAt: null },
      { channel: "email", connected: false, sentToday: 0, dailyQuota: null, lastSentAt: null },
    ];
    const digests: DigestSchedule[] = [
      { id: "d1", label: "Owners", mode: "daily", recipientCount: 3, lastSentAt: null },
      { id: "d2", label: "CAs", mode: "off", recipientCount: 1, lastSentAt: null },
    ];
    expect(connectedCount(channels)).toBe(1);
    expect(connectedCount([])).toBe(0);
    expect(activeDigestCount(digests)).toBe(1);
  });
});
