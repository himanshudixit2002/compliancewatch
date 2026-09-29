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

/** The registry entry for an admin path that has no page file, or null. */
function matchAdminScreen(slug: string[]): ScreenMatch | null {
  const match = matchScreen(`/admin/${slug.map(encodeURIComponent).join("/")}`);
  if (match === null || match.screen.section !== "admin" || match.screen.status === "live") {
    return null;
  }
  return match;
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const match = matchAdminScreen((await params).slug);
  return match === null ? {} : { title: match.screen.title };
}

// Every waiting or planned admin tool resolves here and shows what it waits for.
export default async function NotAvailableAdminPage({ params }: { params: Promise<Params> }) {
  const match = matchAdminScreen((await params).slug);
  if (match === null) notFound();
  return (
    <NotAvailablePage
      view={toNotAvailableView(match.screen)}
      crumbs={breadcrumbsFor(match.screen.id as ScreenId, match.params)}
      backHref={hrefFor(screenById("admin.home"))}
    />
  );
}
