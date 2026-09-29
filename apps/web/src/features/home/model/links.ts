import { LEGAL_DOCS } from "@/shared/config/legal-docs";
import { navFor } from "@/shared/config/nav";
import type { NavContext } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import type { ScreenStatus } from "@/shared/config/screens";

export interface HomeLink {
  label: string;
  href: string;
}

/** The fixed links every visitor sees: sign in, the sitemap, the internal tools, the legal drafts. */
export interface HomeLinks {
  signIn: string;
  sitemap: string;
  admin: string;
  legal: HomeLink[];
}

export function homeLinks(): HomeLinks {
  const legal = screenById("system.legal");
  return {
    signIn: hrefFor(screenById("system.sign-in")),
    sitemap: hrefFor(screenById("system.sitemap")),
    admin: hrefFor(screenById("admin.home")),
    legal: LEGAL_DOCS.map((doc) => ({ label: doc.title, href: hrefFor(legal, { doc: doc.name }) })),
  };
}

export interface HomeItem {
  id: string;
  title: string;
  href: string;
  status: ScreenStatus;
}

export interface HomeSection {
  key: string;
  label: string;
  items: HomeItem[];
}

/**
 * The sections a signed-in principal may open, with each screen's status, derived from the
 * same navigation the shell shows. An anonymous context yields no sections.
 */
export function homeSectionsFor(ctx: NavContext): HomeSection[] {
  return navFor(ctx).map((section) => ({
    key: section.key,
    label: section.label,
    items: section.items.map((item) => ({
      id: item.id,
      title: item.label,
      href: item.href,
      status: screenById(item.id as Parameters<typeof screenById>[0]).status,
    })),
  }));
}
