import type { Metadata } from "next";
import { HomeView, homeLinks } from "@/features/home";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("system.home");

export const metadata: Metadata = { title: SCREEN.title };

// No session exists yet, so every visitor sees the landing; the session package passes the
// signed-in sections here.
export default function HomePage() {
  return <HomeView links={homeLinks()} sections={null} />;
}
