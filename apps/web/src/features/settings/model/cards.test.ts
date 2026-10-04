import { describe, expect, it } from "vitest";
import { SCREENS } from "@/shared/config/screens";
import { isMessageKey } from "@/shared/i18n";
import { aboutKey, settingsIndexView } from "./cards";

describe("settingsIndexView", () => {
  it("lists an owner's settings and account pages in nav order, without the index itself", () => {
    const view = settingsIndexView({ roles: ["owner"], tenantKind: "business" });
    expect(view.settings.map((card) => card.id)).toEqual([
      "owner.settings.consents",
      "owner.settings.notifications",
      "owner.settings.billing",
      "owner.settings.notification-recipients",
      "owner.settings.data-rights",
      "owner.settings.team",
      "owner.settings.activity",
      "ca.settings.api-keys",
    ]);
    expect(view.account.map((card) => card.id)).toEqual(["account.home", "account.mfa"]);
    const consents = view.settings[0];
    expect(consents).toMatchObject({
      title: "Consents",
      href: "/settings/consents",
      status: "live",
    });
    expect(consents?.description).not.toBe("");
  });

  it("leaves out what the role or the tenant kind may not open", () => {
    const staff = settingsIndexView({ roles: ["staff"], tenantKind: "business" });
    expect(staff.settings.map((card) => card.id)).toEqual([
      "owner.settings.consents",
      "owner.settings.notifications",
    ]);
    const caAdmin = settingsIndexView({ roles: ["ca_admin"], tenantKind: "ca_firm" });
    expect(caAdmin.settings.map((card) => card.id)).toContain("ca.settings.webhooks");
    expect(caAdmin.settings.map((card) => card.id)).toContain("ca.settings.digests");
  });

  it("has a sentence for every settings and account page", () => {
    const pages = SCREENS.filter(
      (screen) =>
        (screen.nav?.group === "settings" || screen.nav?.group === "account") &&
        screen.id !== "owner.settings",
    );
    expect(pages.length).toBeGreaterThan(0);
    for (const screen of pages) {
      expect(isMessageKey(aboutKey(screen.id)), `${aboutKey(screen.id)} in en.json`).toBe(true);
    }
  });

  it("describes a page without a sentence with nothing rather than failing", () => {
    const [consents] = SCREENS.filter((screen) => screen.id === "owner.settings.consents");
    const view = settingsIndexView({ roles: ["owner"], tenantKind: "business" }, [
      { ...(consents as (typeof SCREENS)[number]), id: "owner.settings.example" },
    ]);
    expect(view.settings[0]?.description).toBe("");
  });
});
