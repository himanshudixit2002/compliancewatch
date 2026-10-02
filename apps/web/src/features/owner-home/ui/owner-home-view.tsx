"use client";

import Link from "next/link";
import type { Route } from "next";
import { Button, Card, ProgressBar } from "@compliancewatch/ui";
import type { OwnerHomeView } from "@/features/owner-home/model/owner-home";

export interface OwnerHomeViewProps {
  view: OwnerHomeView;
  businessesHref: Route;
  onboardingHref: Route;
}

function StatCard({
  label,
  value,
  href,
}: {
  label: string;
  value: number | string;
  href: Route;
}) {
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-sm font-medium text-fg-muted">{label}</span>
      <span className="text-2xl font-semibold text-fg">{value}</span>
      <Button asChild variant="ghost" size="sm" className="self-start">
        <Link href={href}>View</Link>
      </Button>
    </Card>
  );
}

/** The owner or CA home: a stat strip, a CTA, and a quick-start card. */
export function OwnerHomeView({ view, businessesHref, onboardingHref }: OwnerHomeViewProps) {
  const stats = [
    { label: "Pending review", value: view.pendingReview, href: "/admin/review/queue" },
    { label: "Open obligations", value: view.openObligations, href: "/businesses" },
    { label: "Upcoming deadlines", value: view.upcomingDeadlines, href: "/businesses" },
    { label: "Recent changes", value: view.recentChanges, href: "/changes" },
  ];

  return (
    <div data-slot="owner-home" className="flex flex-col gap-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <StatCard key={stat.label} {...stat} />
        ))}
      </div>

      {view.hasBusinesses ? (
        <Card className="flex flex-col gap-3">
          <h2 className="text-base font-semibold text-fg">Get started with ComplianceWatch</h2>
          <p className="max-w-prose text-sm text-fg-muted">
            Set up your first business to start receiving regulatory updates and obligations.
          </p>
          <Button asChild>
            <Link href={onboardingHref}>Add your first business</Link>
          </Button>
        </Card>
      ) : (
        <Card className="flex flex-col gap-3">
          <h2 className="text-base font-semibold text-fg">Welcome to ComplianceWatch</h2>
          <p className="max-w-prose text-sm text-fg-muted">
            Track regulatory changes, manage obligations, and stay compliant. Start by adding your
            first business.
          </p>
          <div className="flex gap-3">
            <Button asChild>
              <Link href={businessesHref}>Your businesses</Link>
            </Button>
            <Button asChild variant="secondary">
              <Link href={onboardingHref}>Add a business</Link>
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
