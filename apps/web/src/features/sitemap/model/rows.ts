import { toAwaitedFileItem, toAwaitedItem } from "@/entities/screen/mappers";
import { roleLabels } from "@/entities/screen/mappers";
import type { AwaitedItemView } from "@/entities/screen/types";
import { LEGAL_DOCS } from "@/shared/config/legal-docs";
import { SCREENS, hrefFor, isCatchAll, routeParams } from "@/shared/config/screens";
import type { Screen, ScreenKind, ScreenSection, ScreenStatus } from "@/shared/config/screens";

export interface SitemapLink {
  label: string;
  href: string;
}

export interface SitemapRow {
  id: string;
  title: string;
  route: string;
  kind: ScreenKind;
  /** Set when the route has no parameters, so the screen (or its notice) can be opened. */
  href: string | null;
  /** Concrete pages under a parameterised route, such as the legal documents. */
  links: SitemapLink[];
  roles: string[];
  status: ScreenStatus;
  waitsFor: AwaitedItemView[];
  guideRef: string;
}

export interface SitemapSection {
  key: ScreenSection;
  rows: SitemapRow[];
}

export const SECTION_ORDER: readonly ScreenSection[] = [
  "owner",
  "ca",
  "account",
  "admin",
  "system",
];

function hrefOf(screen: Screen): string | null {
  if (screen.kind !== "page" || isCatchAll(screen.route)) return null;
  return routeParams(screen.route).length === 0 ? hrefFor(screen) : null;
}

function linksOf(screen: Screen): SitemapLink[] {
  if (screen.id !== "system.legal") return [];
  return LEGAL_DOCS.map((doc) => ({ label: doc.title, href: hrefFor(screen, { doc: doc.name }) }));
}

export function toSitemapRow(screen: Screen): SitemapRow {
  return {
    id: screen.id,
    title: screen.title,
    route: screen.route,
    kind: screen.kind,
    href: hrefOf(screen),
    links: linksOf(screen),
    roles: roleLabels(screen.roles),
    status: screen.status,
    waitsFor: [
      ...screen.awaits.map(toAwaitedItem),
      ...(screen.awaitsFiles ?? []).map(toAwaitedFileItem),
    ],
    guideRef: screen.guideRef,
  };
}

/** Every registry entry except the catch-all plumbing, grouped by section in display order. */
export function sitemapSections(screens: readonly Screen[] = SCREENS): SitemapSection[] {
  return SECTION_ORDER.map((key) => ({
    key,
    rows: screens
      .filter((screen) => screen.section === key && !isCatchAll(screen.route))
      .map(toSitemapRow),
  })).filter((section) => section.rows.length > 0);
}

export function countRows(sections: readonly SitemapSection[]): number {
  return sections.reduce((total, section) => total + section.rows.length, 0);
}
