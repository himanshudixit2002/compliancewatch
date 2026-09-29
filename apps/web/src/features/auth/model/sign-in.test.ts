import { describe, expect, it } from "vitest";
import { ROLES } from "@/shared/config/roles";
import {
  DEFAULT_TENANT_KIND,
  FIELD_NAMES,
  isKnownTenantKind,
  parseFakeSignInForm,
  roleOptionsFor,
  signInFormOptions,
  tenantKindMessageKey,
} from "./sign-in";

function form(entries: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    for (const item of Array.isArray(value) ? value : [value]) data.append(key, item);
  }
  return data;
}

describe("roleOptionsFor", () => {
  it("lists the roles each tenant kind allows, labelled, in the registry's order", () => {
    expect(roleOptionsFor("business")).toEqual([
      { value: "owner", label: "Owner" },
      { value: "staff", label: "Staff" },
      { value: "compliance_lead", label: "Compliance lead" },
    ]);
    expect(roleOptionsFor("ca_firm").map((o) => o.value)).toEqual([
      "ca_admin",
      "ca_staff",
      "compliance_lead",
    ]);
    expect(roleOptionsFor("internal").map((o) => o.value)).toEqual([
      "analyst",
      "reviewer",
      "admin",
    ]);
    const all = new Set(
      (["business", "ca_firm", "internal"] as const).flatMap((k) =>
        roleOptionsFor(k).map((o) => o.value),
      ),
    );
    expect([...all].sort()).toEqual([...ROLES].sort());
  });

  it("names the message key of each kind and recognises the kinds", () => {
    expect(tenantKindMessageKey("ca_firm")).toBe("tenantKind.ca_firm");
    expect(isKnownTenantKind("internal")).toBe(true);
    expect(isKnownTenantKind("club")).toBe(false);
    expect(DEFAULT_TENANT_KIND).toBe("business");
  });
});

describe("signInFormOptions", () => {
  it("bundles the field names, the labelled kinds and the roles per kind", () => {
    const options = signInFormOptions();
    expect(options.fields).toEqual(FIELD_NAMES);
    expect(options.defaultKind).toBe("business");
    expect(options.kinds).toEqual([
      { value: "business", label: "Business" },
      { value: "ca_firm", label: "CA firm" },
      { value: "internal", label: "Internal (regulatory team)" },
    ]);
    expect(options.rolesByKind.internal.map((o) => o.label)).toEqual([
      "Analyst",
      "Reviewer",
      "Admin",
    ]);
  });
});

describe("parseFakeSignInForm", () => {
  it("reads the fields, trims the tenant id and drops empty optional values", () => {
    const parsed = parseFakeSignInForm(
      form({
        [FIELD_NAMES.tenantKind]: "business",
        [FIELD_NAMES.roles]: ["owner", "staff"],
        [FIELD_NAMES.displayName]: "Example owner",
        [FIELD_NAMES.tenantId]: " 00000000-0000-4000-8000-000000000002 ",
        [FIELD_NAMES.next]: "/account",
      }),
    );
    expect(parsed).toEqual({
      ok: true,
      value: {
        tenantKind: "business",
        roles: ["owner", "staff"],
        displayName: "Example owner",
        tenantId: "00000000-0000-4000-8000-000000000002",
        next: "/account",
      },
    });
    const sparse = parseFakeSignInForm(
      form({ [FIELD_NAMES.tenantId]: "  ", [FIELD_NAMES.next]: "" }),
    );
    expect(sparse).toEqual({
      ok: true,
      value: { tenantKind: "", roles: [], displayName: "" },
    });
  });

  it("refuses a file where text is expected and names the field", () => {
    const data = form({ [FIELD_NAMES.tenantKind]: "business" });
    data.append(FIELD_NAMES.displayName, new Blob(["x"]), "name.txt");
    data.append(FIELD_NAMES.roles, new Blob(["x"]), "role.txt");
    const parsed = parseFakeSignInForm(data);
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.fieldErrors).toEqual({
      displayName: ["Expected a text value."],
      roles: ["Expected a text value."],
    });
  });
});
