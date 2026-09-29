import type { Route } from "next";
import Link from "next/link";
import { Button, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ScreenStatusChip } from "@/shared/ui/screen-status-chip";
import type { HomeLinks, HomeSection } from "../model/links";

export interface HomeViewProps {
  links: HomeLinks;
  /** null for an anonymous visitor, who sees the landing; otherwise the sections to open. */
  sections: readonly HomeSection[] | null;
}

function Landing({ links }: { links: HomeLinks }) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("common.appName")}
        description={t("common.tagline")}
        actions={
          <Button asChild>
            <Link href={links.signIn as Route}>{t("common.signIn")}</Link>
          </Button>
        }
      />
      <p className="max-w-prose text-fg">{t("home.intro")}</p>
      <p className="max-w-prose text-sm text-fg-muted">{t("home.signInPrompt")}</p>
    </div>
  );
}

function Sections({ sections }: { sections: readonly HomeSection[] }) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("home.title")} description={t("home.sections")} />
      {sections.map((section) => (
        <section key={section.key} aria-labelledby={`home-${section.key}`}>
          <h2 id={`home-${section.key}`} className="mb-2 text-lg font-semibold text-fg">
            {section.label}
          </h2>
          <ul className="flex flex-col gap-2">
            {section.items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-2">
                <Link href={item.href as Route} className="text-primary hover:underline">
                  {item.title}
                </Link>
                <ScreenStatusChip status={item.status} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** The home page: a landing with a sign-in link, or the sections a session may open. */
export function HomeView({ links, sections }: HomeViewProps) {
  return (
    <div data-slot="home" className="flex flex-col gap-10">
      {sections === null ? <Landing links={links} /> : <Sections sections={sections} />}
      <section aria-labelledby="home-more" className="flex flex-col gap-3">
        <h2 id="home-more" className="text-lg font-semibold text-fg">
          {t("home.more")}
        </h2>
        <ul className="flex flex-col gap-1 text-sm">
          <li>
            <Link href={links.sitemap as Route} className="text-primary hover:underline">
              {t("home.sitemapLink")}
            </Link>
          </li>
          <li>
            <Link href={links.admin as Route} className="text-primary hover:underline">
              {t("home.adminLink")}
            </Link>
          </li>
        </ul>
        <h3 className="text-sm font-medium text-fg-muted">{t("home.legalDocs")}</h3>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {links.legal.map((link) => (
            <li key={link.href}>
              <Link href={link.href as Route} className="text-primary hover:underline">
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
