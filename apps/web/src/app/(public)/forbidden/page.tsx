import type { Metadata } from "next";
import { ForbiddenView } from "@/features/system-pages";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("system.forbidden");

export const metadata: Metadata = { title: SCREEN.title };

export default function ForbiddenPage() {
  return <ForbiddenView />;
}
