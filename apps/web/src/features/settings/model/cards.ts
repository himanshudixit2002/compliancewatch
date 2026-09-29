import type { Principal, TenantKind } from "@/shared/config/roles";
import { SCREENS, hrefFor, isVisibleTo, routeParams } from "@/shared/config/screens";
import type { Screen, ScreenStatus } from "@/shared/config/screens";
import { isMessageKey, t } from "@/shared/i18n";

/**
 * The settings index: every settings page and account page the session may open, from the
 * registry, in their navigation order, each with its status and one sentence on what it is
 * for. A page that is not built yet is listed too; its link leads to the notice that names the
 * route it waits for. The index itself sits in the account group (so the header links to it)
 * and is left out of its own list.
 */
export const SETTINGS_INDEX_ID = "owner.settings";

export interface SettingsCard {
  id: string;
  title: string;
  href: string;
  status: ScreenStatus;
  description: string;
}

export interface SettingsIndexView {
  settings: SettingsCard[];
  account: SettingsCard[];
}

/** The i18n key of a card's sentence (message keys use "_" where ids use "-"). */
export function aboutKey(id: string): string {
  return `settings.about.${id.replace(/-/g, "_")}`;
}

function cardsOf(
  group: "settings" | "account",
  principal: Principal & { tenantKind: TenantKind },
  screens: readonly Screen[],
): SettingsCard[] {
  return screens
    .filter(
      (screen) =>
        screen.kind === "page" &&
        screen.nav?.group === group &&
        screen.id !== SETTINGS_INDEX_ID &&
        routeParams(screen.route).length === 0 &&
        isVisibleTo(screen, principal.roles, principal.tenantKind),
    )
    .sort((a, b) => (a.nav?.order ?? 0) - (b.nav?.order ?? 0))
    .map((screen) => {
      const key = aboutKey(screen.id);
      return {
        id: screen.id,
        title: screen.title,
        href: hrefFor(screen),
        status: screen.status,
        description: isMessageKey(key) ? t(key) : "",
      };
    });
}

export function settingsIndexView(
  principal: Principal & { tenantKind: TenantKind },
  screens: readonly Screen[] = SCREENS,
): SettingsIndexView {
  return {
    settings: cardsOf("settings", principal, screens),
    account: cardsOf("account", principal, screens),
  };
}
