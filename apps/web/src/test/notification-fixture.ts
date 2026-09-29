import type { PreferenceDto, TemplateDto } from "@/entities/notification/types";

/**
 * Notification service bodies for unit tests: an obviously synthetic number and address, and
 * template rows with placeholder bodies. The e2e suite reads the real service.
 */
export const WHATSAPP_KEY = "910000000000";
export const EMAIL_KEY = "owner@example.com";

export function preferenceDto(overrides: Partial<PreferenceDto> = {}): PreferenceDto {
  return {
    channel: "whatsapp",
    recipient: WHATSAPP_KEY,
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
