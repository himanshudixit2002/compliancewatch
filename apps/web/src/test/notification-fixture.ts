import type { PreferenceDto, TemplateDto } from "@/entities/notification/types";

/**
 * Notification service bodies for unit tests: an obviously synthetic number and address, and
 * template rows with placeholder bodies. The e2e suite reads the real service.
 */
export const WHATSAPP_KEY = "910000000000";
export const EMAIL_KEY = "owner@example.com";

export function preferenceDto(overrides: Partial<PreferenceDto> = {}): PreferenceDto {
  const channel = overrides.channel ?? "whatsapp";
  const recipient = overrides.recipient ?? WHATSAPP_KEY;
  return {
    channel,
    recipient,
    // The address as the service stores it: "+<digits>" on WhatsApp, lower case for email.
    address: channel === "email" ? recipient.toLowerCase() : `+${recipient.replace(/\D/g, "")}`,
    opted_in: true,
    source: "web_onboarding",
    language: "en",
    quiet_hours_start: "21:00",
    quiet_hours_end: "08:00",
    updated_at: "2000-01-01T00:00:00Z",
    ...overrides,
  };
}

export function templateDto(
  channel: TemplateDto["channel"],
  language: string,
  key = "example_template",
): TemplateDto {
  return {
    key,
    channel,
    language,
    status: "draft",
    meta_name: "",
    placeholders: [],
    body: "Example body",
  };
}

export const TEMPLATE_DTOS: TemplateDto[] = [
  templateDto("whatsapp", "en"),
  templateDto("whatsapp", "hi"),
  templateDto("email", "en"),
];
