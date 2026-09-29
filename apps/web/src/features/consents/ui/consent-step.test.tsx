import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { consentSummaryFromDto } from "@/entities/consent/mappers";
import type { ActionState } from "@/shared/lib/action-state";
import { ACCEPTED_STATES, VERSIONS, grantedState, summaryDto } from "@/test/consent-fixture";
import { consentStepView } from "../model/consent-step";
import type { DocumentVersions } from "../model/purposes";
import { ConsentStep } from "./consent-step";

const action = vi.fn(async (): Promise<ActionState> => ({ status: "idle" }));

function renderStep(states = summaryDto(), versions: DocumentVersions = VERSIONS) {
  const view = consentStepView(consentSummaryFromDto(states), versions, "business");
  return render(
    <ConsentStep
      title="Get started"
      view={view}
      action={action}
      continueHref="/onboarding/business"
      documentHref={(name) => `/legal/${name}`}
      whatsappField="whatsapp_number"
      settingsHref="/settings/consents"
    />,
  );
}

describe("ConsentStep", () => {
  it("shows the first step, the draft documents with their versions and the form", async () => {
    const { container } = renderStep();
    expect(screen.getByRole("heading", { level: 1, name: "Get started" })).toBeDefined();
    const steps = screen.getByRole("navigation", { name: "Onboarding steps" });
    expect(steps.querySelector("[aria-current='step']")?.textContent).toContain("Consents");
    const draft = container.querySelector("[data-slot='draft-banner']");
    expect(draft?.textContent).toContain("Draft - to be reviewed by a lawyer");
    expect(draft?.textContent).toContain("Privacy notice 9.9-draft, WhatsApp consent 9.8-draft");
    expect(container.querySelector("[data-slot='consent-form']")).not.toBeNull();
    const links = [...container.querySelectorAll("[data-slot='consent-form'] a")].map((link) =>
      link.getAttribute("href"),
    );
    expect(new Set(links)).toEqual(
      new Set(["/legal/terms-of-service", "/legal/privacy-notice", "/legal/whatsapp-consent"]),
    );
    expect(
      await runAxe(container.querySelector("[data-slot='draft-banner']") as Element),
    ).toHaveNoViolations();
  });

  it("shows what was agreed and the way on once the required purposes are granted", async () => {
    const final = {
      "privacy-notice": { ...VERSIONS["privacy-notice"], isDraft: false },
      "terms-of-service": VERSIONS["terms-of-service"],
      "whatsapp-consent": { ...VERSIONS["whatsapp-consent"], isDraft: false },
    };
    const { container } = renderStep(summaryDto(ACCEPTED_STATES), final);
    expect(container.querySelector("[data-slot='draft-banner']")).toBeNull();
    expect(container.querySelector("[data-slot='consent-form']")).toBeNull();
    const accepted = container.querySelector("[data-slot='consent-accepted']") as HTMLElement;
    expect(accepted.textContent).toContain(
      "Terms of service: terms-of-service@9.9, recorded 1 Jan 2000, 5:30 am IST",
    );
    expect(accepted.textContent).toContain("append-only");
    expect(
      screen.getByRole("link", { name: "Continue to your business" }).getAttribute("href"),
    ).toBe("/onboarding/business");
    expect(await runAxe(accepted)).toHaveNoViolations();
  });

  it("asks again only for what a new version changed and shows the rest as agreed", () => {
    // The terms moved to a new Version line; the rest is still granted at its current version.
    const { container } = renderStep(
      summaryDto([
        grantedState("terms", "terms-of-service@9.0"),
        grantedState("privacy_notice", "privacy-notice@9.9-draft"),
        grantedState("profile_processing", "privacy-notice@9.9-draft"),
        grantedState("whatsapp_reminders", "whatsapp-consent@9.8-draft"),
      ]),
    );
    expect(container.querySelector("[data-slot='consent-accepted']")).toBeNull();
    expect(
      screen
        .getAllByRole("checkbox")
        .map((box) => box.closest("[data-purpose]")?.getAttribute("data-purpose")),
    ).toEqual(["terms", "email_reminders", "analytics"]);
    const agreed = [...container.querySelectorAll("[data-slot='consent-agreed']")];
    expect(agreed.map((line) => line.getAttribute("data-purpose"))).toEqual([
      "privacy_notice",
      "profile_processing",
      "whatsapp_reminders",
    ]);
    expect(agreed[2]?.textContent).toContain("Agreed on 1 Jan 2000, 5:30 am IST:");
    expect(
      screen
        .getByRole("link", { name: "Withdraw it in the consent settings" })
        .getAttribute("href"),
    ).toBe("/settings/consents");
  });
});
