import type { Metadata } from "next";
import { SitemapView, sitemapSections } from "@/features/sitemap";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("system.sitemap");

export const metadata: Metadata = { title: SCREEN.title };

export default function SitemapPage() {
  return <SitemapView sections={sitemapSections()} />;
}
