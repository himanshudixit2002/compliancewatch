import { describe, expect, it } from "vitest";
import { ROLES } from "@/shared/config/roles";
import {
  DEFAULT_TENANT_KIND,
  FIELD_NAMES,
  isKnownTenantKind,
  normaliseSignInPhone,
  parseCodeForm,
  parseEmailForm,
  parseFakeSignInForm,
  parseMfaForm,
  parsePhoneForm,
  parseSignUpForm,
  readSignInMethod,
  roleOptionsFor,
  signInFormOptions,
  signInNoticeKey,
  signInRefusalKey,
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

describe("signInRefusalKey", () => {
  it("gives the refusals their plain reasons and nothing for other problems", () => {
    expect(signInRefusalKey("identity-tenant-deleting")).toBe("signIn.refusal.tenantDeleting");
    expect(signInRefusalKey("identity-user-disabled")).toBe("signIn.refusal.userDisabled");
    expect(signInRefusalKey("identity-subject-registered")).toBe(
      "signIn.refusal.subjectRegistered",
    );
    expect(signInRefusalKey("identity-mfa-required")).toBeUndefined();
    expect(signInRefusalKey("toString")).toBeUndefined();
  });
});

describe("readSignInMethod and signInNoticeKey", () => {
  it("shows the method the query names when the provider offers it, else the first on offer", () => {
    expect(readSignInMethod("email", ["dev", "phone", "email"])).toBe("email");
    expect(readSignInMethod("dev", ["phone", "email"])).toBe("phone");
    expect(readSignInMethod(undefined, ["dev", "phone", "email"])).toBe("dev");
    expect(readSignInMethod(["email"], ["phone", "email"])).toBe("phone");
    expect(readSignInMethod("nonsense", ["phone"])).toBe("phone");
    expect(readSignInMethod(undefined, [])).toBe("phone");
  });

  it("words the reason and error queries, reason first", () => {
    expect(signInNoticeKey({ reason: "signed-out" })).toBe("signIn.notice.signedOut");
    expect(signInNoticeKey({ error: "link-expired" })).toBe("signIn.notice.linkExpired");
    expect(signInNoticeKey({ error: "registered" })).toBe("signIn.refusal.subjectRegistered");
    expect(signInNoticeKey({ error: "disabled" })).toBe("signIn.refusal.userDisabled");
    expect(signInNoticeKey({ error: "pending-expired" })).toBe("signIn.notice.pendingExpired");
    expect(signInNoticeKey({ reason: "signed-out", error: "link-expired" })).toBe(
      "signIn.notice.signedOut",
    );
    expect(signInNoticeKey({ reason: "nope" })).toBeUndefined();
    expect(signInNoticeKey({})).toBeUndefined();
    expect(signInNoticeKey({ error: ["link-expired"] })).toBeUndefined();
  });
});

describe("the phone, code, email, sign-up and second-factor forms", () => {
  it("normalise an Indian mobile number and keep an international one", () => {
    expect(normaliseSignInPhone("98765 43210")).toBe("+919876543210");
    expect(normaliseSignInPhone("098765-43210")).toBe("+919876543210");
    expect(normaliseSignInPhone("+91 (98765) 43210")).toBe("+919876543210");
    expect(normaliseSignInPhone("+44 7700 900123")).toBe("+447700900123");
    expect(normaliseSignInPhone("12345")).toBe("12345");
  });

  it("read the phone and code steps", () => {
    expect(parsePhoneForm(form({ phone: "9876543210", next: "/account" }))).toEqual({
      ok: true,
      value: { phone: "+919876543210", next: "/account" },
    });
    expect(parsePhoneForm(form({ phone: "" }))).toEqual({
      ok: false,
      fieldErrors: { phone: ["Enter your mobile number."] },
    });
    expect(parsePhoneForm(form({ phone: "12" })).ok).toBe(false);
    expect(parseCodeForm(form({ phone: "+919876543210", code: " 123 456 " }))).toEqual({
      ok: true,
      value: { phone: "+919876543210", code: "123456" },
    });
    expect(parseCodeForm(form({ phone: "+919876543210", code: "12345" }))).toEqual({
      ok: false,
      fieldErrors: { code: ["Enter the 6 digits of the code."] },
    });
    expect(parseCodeForm(form({ phone: "", code: "123456" })).ok).toBe(false);
  });

  it("read the email step", () => {
    expect(parseEmailForm(form({ email: " Owner@Example.test " }))).toEqual({
      ok: true,
      value: { email: "owner@example.test" },
    });
    expect(parseEmailForm(form({ email: "" }))).toEqual({
      ok: false,
      fieldErrors: { email: ["Enter your email address."] },
    });
    expect(parseEmailForm(form({ email: "nope" })).ok).toBe(false);
  });

  it("read the sign-up form and name each field that fails", () => {
    expect(
      parseSignUpForm(
        form({ kind: "ca_firm", name: " Example CA ", displayName: " Example admin " }),
      ),
    ).toEqual({
      ok: true,
      value: { kind: "ca_firm", name: "Example CA", displayName: "Example admin" },
    });
    const refused = parseSignUpForm(form({ kind: "club", name: "", displayName: "x".repeat(201) }));
    expect(refused.ok).toBe(false);
    if (!refused.ok) {
      expect(Object.keys(refused.fieldErrors).sort()).toEqual(["displayName", "kind", "name"]);
    }
  });

  it("read the second-factor forms, the code only when asked", () => {
    expect(parseMfaForm(form({ next: "/admin" }), { code: false })).toEqual({
      ok: true,
      value: { code: "", next: "/admin" },
    });
    expect(parseMfaForm(form({ code: "12", factorId: "f1" }), { code: true }).ok).toBe(false);
    expect(
      parseMfaForm(form({ code: "123 456", factorId: " f1 ", friendlyName: " Work phone " }), {
        code: true,
      }),
    ).toEqual({
      ok: true,
      value: { code: "123456", factorId: "f1", friendlyName: "Work phone" },
    });
  });
});
