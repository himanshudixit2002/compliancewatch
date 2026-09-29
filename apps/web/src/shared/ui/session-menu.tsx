import type { Route } from "next";
import Link from "next/link";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { SignOutButton } from "./sign-out-button";

export interface SessionMenuProps {
  /** The render-safe session (a SessionDto); only the name is shown. */
  session: { displayName: string };
}

/** The header's account controls for a signed-in user: the name (a link to /account) and sign out. */
export function SessionMenu({ session }: SessionMenuProps) {
  return (
    <nav aria-label={t("nav.account")} data-slot="session-menu" className="flex items-center gap-2">
      <Link
        href={hrefFor(screenById("account.home")) as Route}
        className="max-w-48 truncate text-sm font-medium text-fg hover:underline"
      >
        {session.displayName}
      </Link>
      <SignOutButton variant="ghost" />
    </nav>
  );
}
