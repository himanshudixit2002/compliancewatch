import { describe, expect, it } from "vitest";
import { recipientFromDto, templateFromDto } from "@/entities/notification/mappers";
import {
  BUSINESS_ID,
  RECIPIENT_ID,
  TEMPLATE_DTOS,
  recipientDto,
} from "@/test/notification-fixture";
import { recipientName, recipientsPageView, type RecipientsPageInput } from "./page";

const OTHER_ID = "00000000-0000-4000-8000-0000000000b2";
const NEW_ID = "00000000-0000-4000-8000-0000000000e9";
const PAGE = "/settings/notifications/recipients";

const BUSINESSES = [
  {
    id: BUSINESS_ID,
    name: "Example business",
    pan: "AAAPE0001Z",
    gstins: [],
    updatedAt: "2000-01-01T00:00:00Z",
  },
  {
    id: OTHER_ID,
    name: "Example second business",
    pan: "AAAPE0002Z",
    gstins: [],
    updatedAt: "2000-01-01T00:00:00Z",
  },
];

function input(overrides: Partial<RecipientsPageInput> = {}): RecipientsPageInput {
  return {
    tenantKind: "business",
    businesses: BUSINESSES,
    moreBusinesses: false,
    selected: { id: BUSINESS_ID, name: "Example business" },
    recipients: [recipientFromDto(recipientDto())],
    moreRecipients: false,
    templates: TEMPLATE_DTOS.map(templateFromDto),
    editing: null,
    editMissing: false,
    newRecipientId: NEW_ID,
    pageHref: PAGE,
    ...overrides,
  };
}

describe("recipientsPageView", () => {
  it("lists the business's recipients and offers an empty form for a new one", () => {
    const view = recipientsPageView(input());
    expect(view.rows).toEqual([
      {
        id: RECIPIENT_ID,
        orgLabel: "",
        roleLabel: "Owner",
        addresses: [
          { channel: "whatsapp", channelLabel: "WhatsApp", address: "+910000000000" },
          { channel: "email", channelLabel: "Email", address: "owner@example.com" },
        ],
        businesses: ["Example business"],
        languageLabel: "English",
        deliveryLabel: "As they happen",
        updatedAt: "2000-01-02T05:00:00Z",
        editHref: `${PAGE}?business=${BUSINESS_ID}&edit=${RECIPIENT_ID}`,
      },
    ]);
    expect(view.summary).toEqual({ total: 1, whatsapp: 1, email: 1, byDigest: 0 });
    expect(view.form).toEqual({
      mode: "add",
      recipientId: NEW_ID,
      name: "",
      values: {
        role: "owner",
        language: "en",
        digestMode: "off",
        orgLabel: "",
        addresses: [],
        businessIds: [BUSINESS_ID],
      },
      roles: [
        { value: "owner", label: "Owner" },
        { value: "staff", label: "Staff" },
      ],
      languages: [
        { value: "en", label: "English" },
        { value: "hi", label: "Hindi" },
      ],
      businesses: [
        { value: BUSINESS_ID, label: "Example business" },
        { value: OTHER_ID, label: "Example second business" },
      ],
      addressRows: 2,
    });
  });

  it("fills the form with the recipient being changed, keeping what the lists lack", () => {
    const editing = recipientFromDto(
      recipientDto({
        role: "ca_admin",
        language: "ta",
        digest_mode: "off",
        by_digest: true,
        org_label: "Example firm",
        businesses: [
          { business_id: BUSINESS_ID, label: "Example client" },
          { business_id: "00000000-0000-4000-8000-0000000000b9", label: "" },
        ],
      }),
    );
    const view = recipientsPageView(input({ editing, recipients: [editing] }));
    expect(view.form?.mode).toBe("change");
    expect(view.form?.recipientId).toBe(RECIPIENT_ID);
    expect(view.form?.name).toBe("Example firm");
    expect(view.form?.roles.map((role) => role.value)).toEqual(["owner", "staff", "ca_admin"]);
    expect(view.form?.languages.map((language) => language.value)).toEqual(["en", "hi", "ta"]);
    expect(view.form?.businesses.map((business) => business.label)).toEqual([
      "Example business",
      "Example second business",
      "00000000-0000-4000-8000-0000000000b9",
    ]);
    expect(view.form?.values.businessIds).toEqual([
      BUSINESS_ID,
      "00000000-0000-4000-8000-0000000000b9",
    ]);
    expect(view.form?.addressRows).toBe(3);
    expect(view.rows[0]?.deliveryLabel).toBe("Daily digest, as for every CA firm recipient");
    // Sorted by name for the page; the service lists them by id.
    expect(view.rows[0]?.businesses).toEqual([
      "00000000-0000-4000-8000-0000000000b9",
      "Example business",
    ]);
  });

  it("has no form and no rows for a tenant without a business", () => {
    const view = recipientsPageView(
      input({ businesses: [], selected: null, recipients: [], editMissing: true }),
    );
    expect(view.form).toBeNull();
    expect(view.rows).toEqual([]);
    expect(view.editMissing).toBe(true);
  });

  it("names a link by its label when the tenant's list does not hold the business", () => {
    const view = recipientsPageView(
      input({
        businesses: [],
        recipients: [
          recipientFromDto(
            recipientDto({ businesses: [{ business_id: OTHER_ID, label: "Example label" }] }),
          ),
        ],
      }),
    );
    expect(view.rows[0]?.businesses).toEqual(["Example label"]);
  });
});

describe("recipientName", () => {
  it("is the organisation, or the role without one", () => {
    expect(recipientName({ orgLabel: "Example firm", role: "ca_staff" })).toBe("Example firm");
    expect(recipientName({ orgLabel: "", role: "ca_staff" })).toBe("CA staff");
  });
});
