import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Catalogue } from "@/features/design-catalogue";
import { isLocalOrTest } from "@/server/env";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("system.design");

export const metadata: Metadata = { title: SCREEN.title };

// The gate reads CW_WEB_ENV per request; a build-time answer must never be baked in.
export const dynamic = "force-dynamic";

/** The UI kit catalogue, served only where CW_WEB_ENV is local or test. */
export default function DesignPage() {
  if (!isLocalOrTest()) notFound();
  return <Catalogue />;
}
