import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { consentSummaryFromDto } from "@/entities/consent/mappers";
import type { ActionState } from "@/shared/lib/action-state";
import {
  ACCEPTED_STATES,
  OWNER_ID,
  VERSIONS,
  grantedState,
  recordDto,
  summaryDto,
} from "@/test/consent-fixture";
import { consentSettingsView } from "../model/settings";
import { ConsentSettings } from "./consent-settings";

const action = vi.fn(async (): Promise<ActionState<string>> => ({ status: "idle" }));
const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "owner.settings.consents", href: "/settings/consents", label: "Consents" },
];
const TABS = [
  { id: "owner.settings.consents", href: "/settings/consents", label: "Consents" },
  { id: "owner.settings.billing", href: "/settings/billing", label: "Billing" },
];

function renderSettings(
  summary = summaryDto(),
  options: { tenantKind?: "business" | "ca_firm"; onboardingHref?: string | null } = {},
) {
  const view = consentSettingsView(consentSummaryFromDto(summary), VERSIONS, {
    tenantKind: options.tenantKind ?? "business",
    userId: OWNER_ID,
    whatsappNumber: "+910000000000",
  });
  return render(
    <ConsentSettings
      title="Consents"
      view={view}
      crumbs={CRUMBS}
      tabs={TABS}
      action={action}
      fields={{ purpose: "purpose", change: "change", number: "whatsapp_number" }}
      onboardingHref={options.onboardingHref === undefined ? "/onboarding" : options.onboardingHref}
      dataRightsHref="/settings/data-rights"
      documentHref={(name) => `/legal/${name}`}
    />,
  );
}

describe("ConsentSettings", () => {
  it("shows every purpose as not given, the draft documents, and where to start", async () => {
    const { container } = renderSettings();
    expect(screen.getByRole("heading", { level: 1, name: "Consents" })).toBeDefined();
    expect(container.querySelector("[data-slot='draft-banner']")?.textContent).toContain(
      "Privacy notice 9.9-draft, WhatsApp consent 9.8-draft",
    );
    const states = container.querySelector("[data-slot='consent-states']") as HTMLElement;
    const terms = states.querySelector("[data-purpose='terms']") as HTMLElement;
    expect(terms.textContent).toContain("Not given");
    expect(terms.textContent).toContain("Never recorded");
    expect(terms.textContent).toContain("Required to use the service");
    expect(within(terms).getByRole("link").getAttribute("href")).toBe("/legal/terms-of-service");
    expect(screen.getByRole("button", { name: "Give consent: Product analytics" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "No consent recorded for you yet" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Get started" }).getAttribute("href")).toBe(
      "/onboarding",
    );
    expect(screen.getByRole("link", { name: "Data rights" }).getAttribute("href")).toBe(
      "/settings/data-rights",
    );
    expect(await runAxe(states)).toHaveNoViolations();
  });

  it("lists the history oldest first and offers to withdraw what is given", async () => {
    const { container } = renderSettings(
      summaryDto(
        [
          ...ACCEPTED_STATES.slice(0, 2),
          grantedState("profile_processing", "privacy-notice@9.0"),
          grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft"),
        ],
        [
          recordDto("terms", true, "terms-of-service@9.9"),
          recordDto("analytics", false, "", { recorded_by: null }),
          recordDto("email_reminders", true, "privacy-notice@9.9-draft", {
            recorded_by: "00000000-0000-4000-8000-0000000000aa",
          }),
        ],
      ),
    );
    expect(screen.getByRole("button", { name: "Withdraw: WhatsApp reminders" })).toBeDefined();
    const outdated = container.querySelector("[data-slot='consent-outdated']") as HTMLElement;
    expect(outdated.textContent).toContain(
      "Given for an earlier version; the current one is privacy-notice@9.9-draft.",
    );
    expect(within(outdated).getByRole("link").getAttribute("href")).toBe("/onboarding");
    const history = container.querySelector("[data-slot='consent-history']") as HTMLElement;
    const rows = history.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(3);
    expect(rows[0]?.textContent).toContain("Terms of service");
    expect(rows[0]?.textContent).toContain("You");
    expect(rows[1]?.textContent).toContain("Withdrawn");
    expect(rows[1]?.textContent).toContain("None");
    expect(rows[1]?.textContent).toContain("Not recorded");
    expect(rows[2]?.textContent).toContain("00000000-0000-4000-8000-0000000000aa");
    expect(await runAxe(history)).toHaveNoViolations();
  });

  it("gives a role without the consent step no link to it, and a CA firm no WhatsApp box", () => {
    const { container } = renderSettings(
      summaryDto([grantedState("profile_processing", "privacy-notice@9.0")]),
      { tenantKind: "ca_firm", onboardingHref: null },
    );
    expect(container.querySelector("[data-purpose='whatsapp_reminders']")).toBeNull();
    expect(screen.queryByRole("link", { name: "Get started" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Agree to the current version" })).toBeNull();
    expect(screen.getByText(/Reminders and analytics can be given above/)).toBeDefined();
  });

  it("names why a CA firm cannot give WhatsApp reminders again once withdrawn", () => {
    const { container } = renderSettings(
      summaryDto([grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft", false)]),
      { tenantKind: "ca_firm" },
    );
    const row = container.querySelector("[data-purpose='whatsapp_reminders']") as HTMLElement;
    expect(row.textContent).toContain("Set for each client business, not for the firm.");
  });
});
