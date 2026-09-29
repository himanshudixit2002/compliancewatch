import type { Metadata } from "next";
import { toSessionDto } from "@/entities/session/mappers";
import { AccountView } from "@/features/account";
import { requireScreenSession } from "@/server/dal";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("account.home");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function AccountPage() {
  const session = await requireScreenSession(SCREEN);
  return <AccountView session={toSessionDto(session)} />;
}
