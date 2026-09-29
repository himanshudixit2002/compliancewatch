import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { toNotAvailableView } from "@/entities/screen/mappers";
import { NotAvailablePage } from "@/features/not-available";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, matchScreen, screenById } from "@/shared/config/screens";
import type { ScreenId, ScreenMatch } from "@/shared/config/screens";

interface Params {
  slug: string[];
}

/** The registry entry for a tenant path that has no page file, or null. */
function matchTenantScreen(slug: string[]): ScreenMatch | null {
  const match = matchScreen(`/${slug.map(encodeURIComponent).join("/")}`);
  if (match === null || match.screen.section === "admin" || match.screen.status === "live") {
    return null;
  }
  return match;
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const match = matchTenantScreen((await params).slug);
  return match === null ? {} : { title: match.screen.title };
}

// Every planned, waiting or ready tenant screen resolves here and shows its backend state.
export default async function NotAvailableTenantPage({ params }: { params: Promise<Params> }) {
  const match = matchTenantScreen((await params).slug);
  if (match === null) notFound();
  return (
    <NotAvailablePage
      view={toNotAvailableView(match.screen)}
      crumbs={breadcrumbsFor(match.screen.id as ScreenId, match.params)}
      backHref={hrefFor(screenById("system.home"))}
    />
  );
}
