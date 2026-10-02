import type { Route } from "next";
import Link from "next/link";
import { Button, Card, PageHeader, ProgressBar } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { StatCard } from "@/shared/ui/stat-card";
import { hasBusinesses, onboardingOpen, type OwnerHomeSummary } from "../model/owner-home";

/** Where the home links to; a stat without a link shows its figure only. */
export interface OwnerHomeLinks {
  businesses: Route;
  addBusiness: Route;
  /** Continue the open onboarding; falls back to addBusiness. */
  onboarding?: Route;
  pendingReview?: Route;
  openObligations?: Route;
  upcomingDeadlines?: Route;
  recentChanges?: Route;
}

export interface OwnerHomeViewProps {
  summary: OwnerHomeSummary;
  links: OwnerHomeLinks;
}

function statLink(href: Route | undefined, label: string) {
  if (href === undefined) return undefined;
  return (
    <Link href={href} className="text-primary hover:underline">
      {label}
    </Link>
  );
}

function Welcome({ links }: { links: OwnerHomeLinks }) {
  return (
    <Card className="flex flex-col gap-3 px-6">
      <h2 className="text-lg font-semibold text-fg">{t("ownerHome.welcomeTitle")}</h2>
      <p className="max-w-prose text-sm text-fg-muted">{t("ownerHome.welcomeBody")}</p>
      <Button asChild className="self-start">
        <Link href={links.addBusiness}>{t("ownerHome.addFirstBusiness")}</Link>
      </Button>
    </Card>
  );
}

function Overview({ summary, links }: OwnerHomeViewProps) {
  const stats = [
    {
      key: "pendingReview",
      label: t("ownerHome.pendingReview"),
      link: t("ownerHome.pendingReviewLink"),
      value: summary.pendingReview,
    },
    {
      key: "openObligations",
      label: t("ownerHome.openObligations"),
      link: t("ownerHome.openObligationsLink"),
      value: summary.openObligations,
    },
    {
      key: "upcomingDeadlines",
      label: t("ownerHome.upcomingDeadlines"),
      link: t("ownerHome.upcomingDeadlinesLink"),
      value: summary.upcomingDeadlines,
    },
    {
      key: "recentChanges",
      label: t("ownerHome.recentChanges"),
      link: t("ownerHome.recentChangesLink"),
      value: summary.recentChanges,
    },
  ] as const;
  const onboarding = onboardingOpen(summary) ? summary.onboarding : null;
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <StatCard
            key={stat.key}
            label={stat.label}
            value={stat.value}
            hint={statLink(links[stat.key], stat.link)}
          />
        ))}
      </div>
      {onboarding ? (
        <Card className="flex flex-col gap-3 px-6">
          <h2 className="text-lg font-semibold text-fg">
            {t("ownerHome.onboardingTitle", { name: onboarding.businessName })}
          </h2>
          <ProgressBar
            label={t("ownerHome.onboardingProgress")}
            value={onboarding.answered}
            max={onboarding.total}
            valueText={t("ownerHome.onboardingAnswered", {
              answered: onboarding.answered,
              total: onboarding.total,
            })}
          />
          <Button asChild className="self-start">
            <Link href={links.onboarding ?? links.addBusiness}>
              {t("ownerHome.continueOnboarding")}
            </Link>
          </Button>
        </Card>
      ) : null}
      <div className="flex flex-wrap gap-3">
        <Button asChild>
          <Link href={links.businesses}>
            {t("ownerHome.yourBusinesses", { count: summary.businessesCount })}
          </Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href={links.addBusiness}>{t("ownerHome.addBusiness")}</Link>
        </Button>
      </div>
    </>
  );
}

/**
 * The owner's home. Without a business it invites adding the first one; with businesses it shows
 * the counts across them, any onboarding left to finish, and links to the businesses.
 */
export function OwnerHomeView({ summary, links }: OwnerHomeViewProps) {
  return (
    <div data-slot="owner-home" className="flex flex-col gap-6">
      <PageHeader title={t("ownerHome.title")} description={t("ownerHome.intro")} />
      {hasBusinesses(summary) ? (
        <Overview summary={summary} links={links} />
      ) : (
        <Welcome links={links} />
      )}
    </div>
  );
}
