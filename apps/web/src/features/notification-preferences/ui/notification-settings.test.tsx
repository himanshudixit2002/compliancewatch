import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { consentSummaryFromDto } from "@/entities/consent/mappers";
import { preferenceFromDto, templateFromDto } from "@/entities/notification/mappers";
import type { ActionState } from "@/shared/lib/action-state";
import { grantedState, summaryDto } from "@/test/consent-fixture";
import { EMAIL_KEY, TEMPLATE_DTOS, WHATSAPP_KEY, preferenceDto } from "@/test/notification-fixture";
import { notificationSettingsView, type NotificationSettingsInput } from "../model/view";
import { NotificationSettings } from "./notification-settings";

const idle = vi.fn(async (): Promise<ActionState> => ({ status: "idle" }));

function renderPage(input: Partial<NotificationSettingsInput> = {}) {
  const view = notificationSettingsView({
    recipients: {},
    preferences: {},
    templates: TEMPLATE_DTOS.map(templateFromDto),
    consents: consentSummaryFromDto(summaryDto()),
    ...input,
  });
  return render(
    <NotificationSettings
      title="Notifications"
      view={view}
      crumbs={[
        { id: "owner.settings", href: "/settings", label: "Settings" },
        {
          id: "owner.settings.notifications",
          href: "/settings/notifications",
          label: "Notifications",
        },
      ]}
      tabs={[]}
      chooseRecipient={idle}
      forgetRecipient={vi.fn(async () => undefined)}
      savePreference={idle}
      fields={{
        recipient: { channel: "channel", recipient: "recipient" },
        preference: {
          channel: "channel",
          optedIn: "opted_in",
          language: "language",
          quietStart: "quiet_hours_start",
          quietEnd: "quiet_hours_end",
        },
      }}
      consentsHref="/settings/consents"
    />,
  );
}

describe("NotificationSettings", () => {
  it("asks for a number and an address when this device remembers none", async () => {
    const { container } = renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Notifications" })).toBeDefined();
    const whatsapp = screen.getByRole("region", { name: "WhatsApp" });
    expect(within(whatsapp).getByRole("form", { name: "WhatsApp recipient" })).toBeDefined();
    expect(whatsapp.textContent).toContain("Your consent to WhatsApp reminders is not on file");
    const email = screen.getByRole("region", { name: "Email" });
    expect(email.querySelector("[data-slot='email-note']")?.textContent).toContain(
      "does not deliver email yet",
    );
    expect(
      await runAxe(container.querySelector("[data-channel='whatsapp']") as Element),
    ).toHaveNoViolations();
  });

  it("shows a recorded preference, a recipient with nothing recorded, and a failed read", async () => {
    const { container } = renderPage({
      recipients: { whatsapp: WHATSAPP_KEY, email: EMAIL_KEY },
      preferences: {
        whatsapp: { ok: true, value: preferenceFromDto(preferenceDto({ language: "hi" })) },
        email: { ok: true, value: null },
      },
      consents: consentSummaryFromDto(
        summaryDto([grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft")]),
      ),
    });
    const whatsapp = screen.getByRole("region", { name: "WhatsApp" });
    expect(whatsapp.textContent).toContain("WhatsApp number: +910000000000");
    expect(whatsapp.textContent).toContain("Your consent to WhatsApp reminders is on file.");
    const preference = whatsapp.querySelector("[data-slot='preference']") as HTMLElement;
    expect(preference.textContent).toContain("Opted in");
    expect(preference.textContent).toContain("Hindi");
    expect(preference.textContent).toContain("21:00 to 08:00 IST, across midnight");
    expect(within(whatsapp).getByRole("button", { name: "Use another number" })).toBeDefined();
    expect(
      within(whatsapp).getByRole("form", { name: "Preference for +910000000000" }),
    ).toBeDefined();
    const email = screen.getByRole("region", { name: "Email" });
    expect(email.textContent).toContain("Nothing is recorded for this recipient");
    expect(within(email).getByRole("button", { name: "Use another address" })).toBeDefined();
    expect(
      await runAxe(container.querySelector("[data-channel='whatsapp']") as Element),
    ).toHaveNoViolations();
  });

  it("shows a failed preference read without the form", () => {
    renderPage({
      recipients: { email: EMAIL_KEY },
      preferences: {
        email: { ok: false, error: { message: "Example failure", requestId: "req-1" } },
      },
    });
    const email = screen.getByRole("region", { name: "Email" });
    expect(email.textContent).toContain("Example failure");
    expect(email.textContent).toContain("req-1");
    expect(within(email).queryByRole("form", { name: /Preference for/ })).toBeNull();
  });
});
