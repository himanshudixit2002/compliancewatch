import { describe, expect, it } from "vitest";
import { t } from "@/shared/i18n";
import {
  byDueDate,
  overdueCount,
  reminderChannelKey,
  reminderStatusKey,
  reminderTone,
} from "./reminders";
import type { Reminder, ReminderStatus } from "./reminders";

const STATUSES: readonly ReminderStatus[] = ["upcoming", "sent", "acknowledged", "overdue"];

function reminder(id: string, dueAt: string, status: ReminderStatus = "upcoming"): Reminder {
  return {
    id,
    title: id,
    description: null,
    dueAt,
    status,
    channel: "email",
    obligationId: null,
  };
}

describe("reminder labels", () => {
  it("gives every status a tone and a label", () => {
    expect(STATUSES.map(reminderTone)).toEqual(["info", "neutral", "success", "danger"]);
    expect(STATUSES.map((status) => t(reminderStatusKey(status)))).toEqual([
      "Upcoming",
      "Sent",
      "Acknowledged",
      "Overdue",
    ]);
  });

  it("names both channels", () => {
    expect(t(reminderChannelKey("whatsapp"))).toBe("WhatsApp");
    expect(t(reminderChannelKey("email"))).toBe("Email");
  });
});

describe("byDueDate", () => {
  it("orders earliest due first, keeping ties in order, without changing the input", () => {
    const items = [
      reminder("late", "2026-10-20T05:00:00Z"),
      reminder("tie-a", "2026-10-11T05:00:00Z"),
      reminder("early", "2026-10-05T05:00:00Z"),
      reminder("tie-b", "2026-10-11T05:00:00Z"),
    ];
    expect(byDueDate(items).map((item) => item.id)).toEqual(["early", "tie-a", "tie-b", "late"]);
    expect(items[0]?.id).toBe("late");
  });
});

describe("overdueCount", () => {
  it("counts only overdue reminders", () => {
    expect(overdueCount([])).toBe(0);
    expect(
      overdueCount(STATUSES.map((status) => reminder(status, "2026-10-01T00:00:00Z", status))),
    ).toBe(1);
  });
});
