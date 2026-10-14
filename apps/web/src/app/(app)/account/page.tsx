import type { Metadata } from "next";
import { toSessionDto } from "@/entities/session/mappers";
import { AccountView, getAccount } from "@/features/account";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";

const SCREEN = screenById("account.home");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

/** The session's facts and what identity's /me adds: email, phone, the tenant's name. */
export default async function AccountPage() {
  const session = await requireScreenSession(SCREEN);
  const read = await getAccount(session);
  const mfaHref = hrefFor(screenById("account.mfa"));
  if (read.kind === "profile") {
    return <AccountView session={toSessionDto(session)} profile={read.profile} mfaHref={mfaHref} />;
  }
  const note =
    read.kind === "unverifiable"
      ? t("account.profileHeaderMode")
      : t("account.profileUnavailable", { message: read.error.message });
  return <AccountView session={toSessionDto(session)} profileNote={note} mfaHref={mfaHref} />;
}
