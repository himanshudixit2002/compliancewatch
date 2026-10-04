import { describe, expect, it } from "vitest";
import { notificationFromDto } from "@/entities/notification/mappers";
import { NOTIFICATION_ID, notificationDto } from "@/test/notification-fixture";
import {
  DELIVERY_STATES,
  channelLabel,
  deliveryLabel,
  deliveryTone,
  maskAddress,
  notificationDetail,
  notificationRows,
  occasionLabel,
  readHistoryFilter,
  stateOptions,
  templateTitle,
} from "./notifications";

describe("delivery states, occasions and channels", () => {
  it("give every state a tone and a label", () => {
    expect(DELIVERY_STATES.map(deliveryTone)).toEqual([
      "neutral",
      "neutral",
      "info",
      "success",
      "success",
      "danger",
      "warning",
    ]);
    expect(DELIVERY_STATES.map(deliveryLabel)).toEqual([
      "Queued",
      "Waiting for the digest",
      "Sent",
      "Delivered",
      "Read",
      "Failed",
      "Suppressed",
    ]);
  });

  it("name the occasions and channels", () => {
    expect(
      (["change_card", "reminder", "closure", "reschedule", "manual"] as const).map(occasionLabel),
    ).toEqual(["Change card", "Reminder", "Closure", "Due date change", "Sent directly"]);
    expect(channelLabel("whatsapp")).toBe("WhatsApp");
    expect(channelLabel("email")).toBe("Email");
    expect(templateTitle("example_due_soon")).toBe("Example due soon");
  });
});

describe("maskAddress", () => {
  it("keeps the last four digits of a number and the first letter and domain of a mailbox", () => {
    expect(maskAddress("whatsapp", "+910000000123")).toBe("*********0123");
    expect(maskAddress("email", "owner@example.com")).toBe("o****@example.com");
    expect(maskAddress("email", "a@example.com")).toBe("a*@example.com");
    expect(maskAddress("email", "no-at-sign")).toBe("********gn");
  });
});

describe("notificationRows", () => {
  it("names each row by its template and links it", () => {
    const rows = notificationRows(
      [notificationFromDto(notificationDto({ template_key: "example_due_soon", attempts: 3 }))],
      (id) => `/n/${id}`,
    );
    expect(rows).toEqual([
      {
        id: NOTIFICATION_ID,
        href: `/n/${NOTIFICATION_ID}`,
        title: "Example due soon",
        templateKey: "example_due_soon",
        occasionLabel: "Sent directly",
        channelLabel: "WhatsApp",
        to: "*********0000",
        state: "failed",
        stateLabel: "Failed",
        tone: "danger",
        attempts: 3,
        createdAt: "2000-01-01T05:00:00Z",
        updatedAt: "2000-01-01T05:00:00Z",
      },
    ]);
  });
});

describe("notificationDetail", () => {
  it("keeps the record's times, the error and the values as text, by key", () => {
    const detail = notificationDetail(
      notificationFromDto(
        notificationDto({
          language: "hi",
          error: "  Example channel error  ",
          params: { title: "Example title", count: 2, flag: true, lines: ["a", "b"] },
          sent_at: "2000-01-01T05:01:00Z",
        }),
      ),
    );
    expect(detail.error).toBe("Example channel error");
    expect(detail.languageLabel).toBe("Hindi");
    expect(detail.params).toEqual([
      { key: "count", value: "2" },
      { key: "flag", value: "true" },
      { key: "lines", value: '["a","b"]' },
      { key: "title", value: "Example title" },
    ]);
    expect(detail.times.map((time) => [time.key, time.at])).toEqual([
      ["created", "2000-01-01T05:00:00Z"],
      ["available", "2000-01-01T05:00:00Z"],
      ["sent", "2000-01-01T05:01:00Z"],
      ["delivered", null],
      ["read", null],
      ["failed", "2000-01-01T05:00:00Z"],
      ["updated", "2000-01-01T05:00:00Z"],
    ]);
    expect(detail.times.map((time) => time.label)).toEqual([
      "Queued",
      "May go out from",
      "Sent",
      "Delivered",
      "Read",
      "Failed",
      "Last change",
    ]);
  });
});

describe("readHistoryFilter", () => {
  it("keeps a known state and a cursor the service could take", () => {
    expect(readHistoryFilter({ state: "failed", cursor: "abc" })).toEqual({
      state: "failed",
      cursor: "abc",
    });
    expect(readHistoryFilter({ state: ["sent", "read"] })).toEqual({ state: "sent" });
    expect(readHistoryFilter({ state: "lost", cursor: "" })).toEqual({});
    expect(readHistoryFilter({ cursor: "x".repeat(513) })).toEqual({});
  });
});

describe("stateOptions", () => {
  it("offers every state first, then each delivery state", () => {
    const options = stateOptions();
    expect(options[0]).toEqual({ value: "", label: "Every state" });
    expect(options.slice(1).map((option) => option.value)).toEqual([...DELIVERY_STATES]);
  });
});
