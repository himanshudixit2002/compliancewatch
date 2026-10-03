import { describe, expect, it } from "vitest";
import {
  AUDIT_CATEGORIES,
  auditCategory,
  auditCategoryLabel,
  auditCategoryOptions,
  describeChange,
  newestFirst,
  type AuditEvent,
} from "./audit";

function event(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: "ev_1",
    actor: "Meera Iyer",
    action: "user.disabled",
    subjectType: "user",
    subjectId: "u_42",
    changes: [],
    at: "2026-04-10T05:00:00Z",
    ...overrides,
  };
}

describe("auditCategory", () => {
  it("takes the category from the domain before the first dot, ignoring case", () => {
    expect(auditCategory("user.disabled")).toBe("user");
    expect(auditCategory("tenant.deletion_requested")).toBe("tenant");
    expect(auditCategory("obligation.status.changed")).toBe("obligation");
    expect(auditCategory("Rule.Published")).toBe("rule");
  });

  it("files anything else under other, including an action without a dot", () => {
    expect(auditCategory("rule_version.published")).toBe("other");
    expect(auditCategory("export")).toBe("other");
    expect(auditCategory("")).toBe("other");
  });
});

describe("category labels", () => {
  it("words every category and offers each as a filter option", () => {
    expect(AUDIT_CATEGORIES.map(auditCategoryLabel)).toEqual([
      "User",
      "Tenant",
      "Obligation",
      "Rule",
      "Other",
    ]);
    expect(auditCategoryOptions()[0]).toEqual({ value: "user", label: "User" });
    expect(auditCategoryOptions().map((option) => option.value)).toEqual(AUDIT_CATEGORIES);
  });
});

describe("describeChange", () => {
  it("words a field that was set, cleared or updated", () => {
    expect(describeChange({ field: "region", before: null, after: "ap-south-1" })).toBe(
      "region set to ap-south-1",
    );
    expect(describeChange({ field: "phone", before: "+919876543210", after: null })).toBe(
      "phone cleared (was +919876543210)",
    );
    expect(describeChange({ field: "status", before: "active", after: "disabled" })).toBe(
      "status: active → disabled",
    );
  });
});

describe("newestFirst", () => {
  it("orders by instant, keeps ties in order and leaves the input as it was", () => {
    const input = [
      event({ id: "old", at: "2026-04-01T05:00:00Z" }),
      event({ id: "new", at: "2026-04-12T05:00:00+05:30" }),
      event({ id: "tie-a", at: "2026-04-05T05:00:00Z" }),
      event({ id: "tie-b", at: "2026-04-05T10:30:00+05:30" }),
    ];
    expect(newestFirst(input).map((item) => item.id)).toEqual(["new", "tie-a", "tie-b", "old"]);
    expect(input.map((item) => item.id)).toEqual(["old", "new", "tie-a", "tie-b"]);
  });
});
