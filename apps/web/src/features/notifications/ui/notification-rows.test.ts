import type { Route } from "next";
import { describe, expect, it } from "vitest";
import { filterNotificationRows } from "./notification-rows";
import type { NotificationRow } from "./notification-rows";

const ROWS: NotificationRow[] = [
  {
    id: "n1",
    subject: "GSTR-3B due on 20 Oct",
    href: "/n/n1" as Route,
    channelLabel: "WhatsApp",
    state: "delivered",
    stateLabel: "Delivered",
    tone: "success",
    recipient: "+919876543210",
    sentLabel: "1 Oct 2026",
  },
  {
    id: "n2",
    subject: "TDS return filed",
    href: "/n/n2" as Route,
    channelLabel: "Email",
    state: "failed",
    stateLabel: "Failed",
    tone: "danger",
    recipient: "owner@example.com",
    sentLabel: "2 Oct 2026",
  },
];

describe("filterNotificationRows", () => {
  it("keeps every row for a blank query", () => {
    expect(filterNotificationRows(ROWS, "")).toBe(ROWS);
    expect(filterNotificationRows(ROWS, "   ")).toBe(ROWS);
  });

  it("matches the subject, recipient, channel and state, ignoring case", () => {
    expect(filterNotificationRows(ROWS, "gstr").map((row) => row.id)).toEqual(["n1"]);
    expect(filterNotificationRows(ROWS, "OWNER@").map((row) => row.id)).toEqual(["n2"]);
    expect(filterNotificationRows(ROWS, " whatsapp ").map((row) => row.id)).toEqual(["n1"]);
    expect(filterNotificationRows(ROWS, "failed").map((row) => row.id)).toEqual(["n2"]);
  });

  it("returns nothing when no field matches", () => {
    expect(filterNotificationRows(ROWS, "income tax")).toEqual([]);
  });
});
