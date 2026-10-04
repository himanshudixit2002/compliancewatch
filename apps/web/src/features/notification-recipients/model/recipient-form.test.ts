import { describe, expect, it } from "vitest";
import {
  MAX_ADDRESSES,
  RECIPIENT_FIELDS,
  addressField,
  channelField,
  normaliseAddress,
  parseRecipientForm,
} from "./recipient-form";

const RECIPIENT = "00000000-0000-4000-8000-0000000000e1";
const BUSINESS = "00000000-0000-4000-8000-0000000000b1";
const OTHER = "00000000-0000-4000-8000-0000000000b2";
const OFFER = {
  roles: ["owner", "staff"] as const,
  languages: ["en", "hi"],
  businessIds: [BUSINESS, OTHER],
};

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [key, value] of entries) data.append(key, value);
  return data;
}

const VALID: [string, string][] = [
  [RECIPIENT_FIELDS.recipientId, RECIPIENT],
  [RECIPIENT_FIELDS.returnBusiness, BUSINESS],
  [RECIPIENT_FIELDS.role, "staff"],
  [RECIPIENT_FIELDS.language, "hi"],
  [RECIPIENT_FIELDS.digestMode, "daily"],
  [RECIPIENT_FIELDS.orgLabel, "  Example firm  "],
  [channelField(0), "whatsapp"],
  [addressField(0), "+91 00000 00001"],
  [channelField(1), "email"],
  [addressField(1), " Desk@Example.com "],
  [channelField(2), "whatsapp"],
  [addressField(2), ""],
  [RECIPIENT_FIELDS.businesses, BUSINESS],
  [RECIPIENT_FIELDS.businesses, OTHER],
  [RECIPIENT_FIELDS.businesses, BUSINESS],
];

describe("parseRecipientForm", () => {
  it("reads the recipient with its addresses in row order, normalised, and its businesses once", () => {
    expect(parseRecipientForm(form(VALID), OFFER)).toEqual({
      ok: true,
      value: {
        recipientId: RECIPIENT,
        returnBusiness: BUSINESS,
        role: "staff",
        language: "hi",
        digestMode: "daily",
        orgLabel: "Example firm",
        addresses: [
          { channel: "whatsapp", address: "+910000000001" },
          { channel: "email", address: "desk@example.com" },
        ],
        businessIds: [BUSINESS, OTHER],
      },
    });
  });

  it("refuses a form without a recipient id as out of date", () => {
    const parsed = parseRecipientForm(
      form(VALID.filter(([key]) => key !== RECIPIENT_FIELDS.recipientId)),
      OFFER,
    );
    expect(parsed).toEqual({
      ok: false,
      formErrors: ["This form is out of date. Reload the page and try again."],
    });
  });

  it("names every field that is wrong", () => {
    const parsed = parseRecipientForm(
      form([
        [RECIPIENT_FIELDS.recipientId, RECIPIENT],
        [RECIPIENT_FIELDS.returnBusiness, "not an id"],
        [RECIPIENT_FIELDS.role, "admin"],
        [RECIPIENT_FIELDS.language, "zz"],
        [RECIPIENT_FIELDS.digestMode, "weekly"],
        [RECIPIENT_FIELDS.orgLabel, "x".repeat(201)],
        [channelField(0), "whatsapp"],
        [addressField(0), "0000"],
        [channelField(1), "email"],
        [addressField(1), "not an address"],
        [channelField(2), "sms"],
        [addressField(2), "+910000000002"],
        [channelField(3), "whatsapp"],
        [addressField(3), "+910000000003"],
        [channelField(4), "whatsapp"],
        [addressField(4), "+91 0000000003"],
        [RECIPIENT_FIELDS.businesses, "00000000-0000-4000-8000-0000000000ff"],
      ]),
      OFFER,
    );
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.fieldErrors).toEqual({
      [RECIPIENT_FIELDS.role]: ["Choose a role."],
      [RECIPIENT_FIELDS.language]: ["Choose one of the languages listed."],
      [RECIPIENT_FIELDS.digestMode]: ["Choose how the reminders are delivered."],
      [RECIPIENT_FIELDS.orgLabel]: ["Use at most 200 characters."],
      [addressField(0)]: ["Enter a WhatsApp number with its country code, starting with +."],
      [addressField(1)]: ["Enter an email address, such as name@example.com."],
      [channelField(2)]: ["Choose WhatsApp or email."],
      [addressField(4)]: ["This address is already listed above."],
      [RECIPIENT_FIELDS.businesses]: ["Choose among the businesses listed."],
    });
  });

  it("asks for an address and a business when there is none", () => {
    const parsed = parseRecipientForm(
      form([
        [RECIPIENT_FIELDS.recipientId, RECIPIENT],
        [RECIPIENT_FIELDS.role, "owner"],
        [RECIPIENT_FIELDS.language, "en"],
        [RECIPIENT_FIELDS.digestMode, "off"],
        [channelField(0), "whatsapp"],
        [addressField(0), "  "],
      ]),
      OFFER,
    );
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.fieldErrors).toEqual({
      [addressField(0)]: ["Give at least one address the reminders can go to."],
      [RECIPIENT_FIELDS.businesses]: ["Choose at least one business."],
    });
  });

  it("reads at most the rows the form can hold", () => {
    const entries: [string, string][] = [
      [RECIPIENT_FIELDS.recipientId, RECIPIENT],
      [RECIPIENT_FIELDS.role, "owner"],
      [RECIPIENT_FIELDS.language, "en"],
      [RECIPIENT_FIELDS.digestMode, "off"],
      [RECIPIENT_FIELDS.businesses, BUSINESS],
    ];
    for (let index = 0; index <= MAX_ADDRESSES; index += 1) {
      entries.push([channelField(index), "email"], [addressField(index), `r${index}@example.com`]);
    }
    const parsed = parseRecipientForm(form(entries), OFFER);
    expect(parsed.ok && parsed.value.addresses).toHaveLength(MAX_ADDRESSES);
    expect(parsed.ok && parsed.value.returnBusiness).toBeNull();
  });
});

describe("normaliseAddress", () => {
  it("keeps a number as +digits and an address in lower case", () => {
    expect(normaliseAddress("whatsapp", "+91-00000 (00004)")).toEqual({
      ok: true,
      address: "+910000000004",
    });
    expect(normaliseAddress("email", "Owner@Example.COM")).toEqual({
      ok: true,
      address: "owner@example.com",
    });
    expect(normaliseAddress("whatsapp", "00000").ok).toBe(false);
  });
});
