import { describe, expect, it } from "vitest";
import {
  businessTone,
  completionRate,
  completionTone,
  emptyDashboard,
  urgentTone,
} from "./dashboard";

const NOW = new Date("2026-10-02T06:00:00Z");

describe("completionRate", () => {
  it("is null when nothing is counted", () => {
    expect(completionRate(emptyDashboard())).toBeNull();
  });

  it("rounds completed over completed, overdue and due this week", () => {
    expect(completionRate({ ...emptyDashboard(), completed: 2, overdue: 1 })).toBe(67);
    expect(completionRate({ ...emptyDashboard(), completed: 3, dueThisWeek: 1 })).toBe(75);
  });
});

describe("completionTone", () => {
  it("maps the rate to a tone", () => {
    expect(completionTone(null)).toBe("neutral");
    expect(completionTone(80)).toBe("success");
    expect(completionTone(50)).toBe("warning");
    expect(completionTone(49)).toBe("danger");
  });
});

describe("businessTone", () => {
  it("is danger with anything overdue, success otherwise", () => {
    const business = { id: "b", name: "B", openObligations: 2, overdueObligations: 0 };
    expect(businessTone(business)).toBe("success");
    expect(businessTone({ ...business, overdueObligations: 1 })).toBe("danger");
  });
});

describe("urgentTone", () => {
  it("is danger for an overdue action and warning otherwise", () => {
    const action = { businessId: "b", obligationId: "o", title: "GSTR-3B", dueDate: "2026-10-01" };
    expect(urgentTone(action, NOW)).toBe("danger");
    expect(urgentTone({ ...action, dueDate: "2026-10-02" }, NOW)).toBe("warning");
    expect(urgentTone({ ...action, dueDate: "2999-01-01" })).toBe("warning");
  });
});
