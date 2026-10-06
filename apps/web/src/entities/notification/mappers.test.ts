import { describe, expect, it } from "vitest";
import { RUN_VERSION_ID, bulkOutDto } from "@/test/engine-admin-fixture";
import { REGISTRATION_ID } from "@/test/obligation-fixture";
import {
  BUSINESS_ID,
  NOTIFICATION_ID,
  OBLIGATION_ID,
  RECIPIENT_ID,
  notificationDto,
  recipientDto,
} from "@/test/notification-fixture";
import {
  CHANNELS,
  DELIVERY_STATES,
  bulkRequestToDto,
  bulkResultFromDto,
  isDeliveryState,
  notificationFromDto,
  notificationPageFromDto,
  emailKeyOf,
  isChannel,
  isRecipientKey,
  messageTemplateFromDto,
  preferenceChangeToDto,
  preferenceFromDto,
  recipientFromDto,
  recipientInputToDto,
  recipientLabel,
  recipientPageFromDto,
  templateFromDto,
  whatsappKeyOf,
  whatsappNumberOf,
} from "./mappers";

describe("notification preference mappers", () => {
  it("maps the service's preference", () => {
    expect(
      preferenceFromDto({
        channel: "whatsapp",
        recipient: "+910000000000",
        address: "+910000000000",
        opted_in: true,
        source: "web_onboarding",
        language: "en",
        quiet_hours_start: "21:00",
        quiet_hours_end: "08:00",
        updated_at: "2000-01-01T00:00:00Z",
      }),
    ).toEqual({
      channel: "whatsapp",
      recipient: "+910000000000",
      optedIn: true,
      source: "web_onboarding",
      language: "en",
      quietHoursStart: "21:00",
      quietHoursEnd: "08:00",
      updatedAt: "2000-01-01T00:00:00Z",
    });
  });

  it("sends only what is set", () => {
    expect(preferenceChangeToDto({ optedIn: true, source: "web_onboarding" })).toEqual({
      opted_in: true,
      source: "web_onboarding",
    });
    expect(
      preferenceChangeToDto({
        optedIn: false,
        source: "web_onboarding",
        language: "hi",
        quietHoursStart: "22:00",
        quietHoursEnd: "07:00",
      }),
    ).toEqual({
      opted_in: false,
      source: "web_onboarding",
      language: "hi",
      quiet_hours_start: "22:00",
      quiet_hours_end: "07:00",
    });
  });
});

describe("recipient keys", () => {
  it("names the channels in display order", () => {
    expect(CHANNELS).toEqual(["whatsapp", "email"]);
    expect(isChannel("email")).toBe(true);
    expect(isChannel("sms")).toBe(false);
  });

  it("keys a WhatsApp number by its digits and an address lowercased", () => {
    expect(whatsappKeyOf("+919800000001")).toBe("919800000001");
    expect(() => whatsappKeyOf("9800000001")).toThrow("not an E.164 number");
    expect(whatsappNumberOf("919800000001")).toBe("+919800000001");
    expect(emailKeyOf("  Owner@Example.COM ")).toBe("owner@example.com");
  });

  it("accepts only the service's own form of a key", () => {
    expect(isRecipientKey("whatsapp", "919800000001")).toBe(true);
    expect(isRecipientKey("whatsapp", "+919800000001")).toBe(false);
    expect(isRecipientKey("whatsapp", "019800000001")).toBe(false);
    expect(isRecipientKey("email", "owner@example.com")).toBe(true);
    expect(isRecipientKey("email", "Owner@example.com")).toBe(false);
    expect(isRecipientKey("email", "owner")).toBe(false);
  });

  it("shows a number with its plus and an address as it is", () => {
    expect(recipientLabel("whatsapp", "919800000001")).toBe("+919800000001");
    expect(recipientLabel("email", "owner@example.com")).toBe("owner@example.com");
  });
});

describe("templateFromDto", () => {
  it("keeps what the settings page needs and leaves the body on the service", () => {
    expect(
      templateFromDto({
        key: "example_template",
        channel: "email",
        language: "en",
        status: "draft",
        meta_name: "",
        placeholders: ["name"],
        body: "Example body {name}",
      }),
    ).toEqual({ key: "example_template", channel: "email", language: "en", status: "draft" });
  });
});

describe("recipient mappers", () => {
  it("maps a recipient with its addresses in the order they are tried", () => {
    expect(recipientFromDto(recipientDto())).toEqual({
      id: RECIPIENT_ID,
      userId: null,
      role: "owner",
      language: "en",
      digestMode: "off",
      byDigest: false,
      orgLabel: "",
      addresses: [
        { channel: "whatsapp", address: "+910000000000" },
        { channel: "email", address: "owner@example.com" },
      ],
      businesses: [{ businessId: BUSINESS_ID, label: "Example business" }],
      createdAt: "2000-01-01T05:00:00Z",
      updatedAt: "2000-01-02T05:00:00Z",
    });
  });

  it("maps a page and keeps its cursor, null on the last page", () => {
    expect(recipientPageFromDto({ items: [recipientDto()], next_cursor: "next" }).nextCursor).toBe(
      "next",
    );
    expect(recipientPageFromDto({ items: [], next_cursor: null })).toEqual({
      items: [],
      nextCursor: null,
    });
  });

  it("sends the whole recipient on a PUT", () => {
    expect(
      recipientInputToDto({
        role: "ca_staff",
        userId: "00000000-0000-4000-8000-0000000000a2",
        language: "hi",
        digestMode: "daily",
        orgLabel: "Example firm",
        addresses: [{ channel: "email", address: "desk@example.com" }],
        businesses: [{ businessId: BUSINESS_ID, label: "Example client" }],
      }),
    ).toEqual({
      role: "ca_staff",
      user_id: "00000000-0000-4000-8000-0000000000a2",
      language: "hi",
      digest_mode: "daily",
      org_label: "Example firm",
      addresses: [{ channel: "email", address: "desk@example.com" }],
      businesses: [{ business_id: BUSINESS_ID, label: "Example client" }],
    });
  });
});

describe("notification mappers", () => {
  it("maps what the service records of a notification", () => {
    expect(
      notificationFromDto(
        notificationDto({
          recipient_id: RECIPIENT_ID,
          params: { example: "Example value" },
          dispatch_id: "00000000-0000-4000-8000-0000000000d1",
          fallback_of: "00000000-0000-4000-8000-0000000000f0",
        }),
      ),
    ).toEqual({
      id: NOTIFICATION_ID,
      businessId: BUSINESS_ID,
      obligationId: OBLIGATION_ID,
      recipientId: RECIPIENT_ID,
      channel: "whatsapp",
      address: "+910000000000",
      occasion: "manual",
      templateKey: "example_template",
      language: "en",
      params: { example: "Example value" },
      state: "failed",
      attempts: 1,
      availableAt: "2000-01-01T05:00:00Z",
      dispatchId: "00000000-0000-4000-8000-0000000000d1",
      providerMessageId: "",
      error: "Example channel error",
      fallbackOf: "00000000-0000-4000-8000-0000000000f0",
      createdAt: "2000-01-01T05:00:00Z",
      updatedAt: "2000-01-01T05:00:00Z",
      sentAt: null,
      deliveredAt: null,
      readAt: null,
      failedAt: "2000-01-01T05:00:00Z",
    });
  });

  it("maps a page and knows the delivery states", () => {
    const page = notificationPageFromDto({ items: [notificationDto()], next_cursor: null });
    expect(page.items[0]?.recipientId).toBeNull();
    expect(page.nextCursor).toBeNull();
    expect(DELIVERY_STATES).toHaveLength(7);
    expect(isDeliveryState("digest_pending")).toBe(true);
    expect(isDeliveryState("lost")).toBe(false);
  });
});

describe("messageTemplateFromDto", () => {
  it("keeps the text, its placeholders and the Meta name with the template's facts", () => {
    expect(
      messageTemplateFromDto({
        key: "example_template",
        channel: "whatsapp",
        language: "hi",
        status: "draft",
        meta_name: "cw_example_template_hi",
        placeholders: ["business_name", "title"],
        body: "Example {business_name}: {title}.",
      }),
    ).toEqual({
      key: "example_template",
      channel: "whatsapp",
      language: "hi",
      status: "draft",
      metaName: "cw_example_template_hi",
      placeholders: ["business_name", "title"],
      body: "Example {business_name}: {title}.",
    });
  });
});

describe("bulk change card mappers", () => {
  it("names each business once, in the order given, for the change card", () => {
    expect(
      bulkRequestToDto(RUN_VERSION_ID, [REGISTRATION_ID, BUSINESS_ID, REGISTRATION_ID]),
    ).toEqual({
      rule_version_id: RUN_VERSION_ID,
      business_ids: [REGISTRATION_ID, BUSINESS_ID],
      kind: "change_card",
    });
  });

  it("maps what became of each business and the counts", () => {
    const result = bulkResultFromDto(
      bulkOutDto({
        skipped_not_affected: 1,
        businesses: [
          ...bulkOutDto().businesses,
          {
            business_id: BUSINESS_ID,
            outcome: "not_affected",
            obligation_id: null,
            queued: 0,
            duplicates: 0,
            unreachable: 0,
          },
        ],
      }),
    );
    expect(result).toMatchObject({
      ruleVersionId: RUN_VERSION_ID,
      queued: 1,
      skippedNotAffected: 1,
      notificationsQueued: 2,
    });
    expect(result.businesses.map((business) => [business.businessId, business.outcome])).toEqual([
      [REGISTRATION_ID, "queued"],
      [BUSINESS_ID, "not_affected"],
    ]);
    expect(result.businesses[1]?.obligationId).toBeNull();
  });
});
