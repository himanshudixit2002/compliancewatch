"use client";

import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  Icon,
  PageHeader,
  StatCard,
  Table,
  Tabs,
  EmptyState,
  SearchInput,
} from "@compliancewatch/ui";
import type { DashboardView } from "../model/dashboard";

export interface DashboardViewProps {
  view: DashboardView;
  businessHref: (id: string) => string;
  obligationHref: (id: string) => Route;
  href: (id: string) => Route;
}

function ComplianceScoreCard({ score }: { score: number }) {
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-fg-muted">Compliance score</div>
          <div className="text-4xl font-bold text-fg mt-1">{score}%</div>
        </div>
        <div className="h-16 w-16 rounded-full flex items-center justify-center bg-success/10">
          <Icon name="shield-check" className="h-8 w-8 text-success" />
        </div>
      </div>
    </Card>
  );
}

function ObligationsSummary({ view }: { view: DashboardView }) {
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Card className="p-4 border-l-4 border-l-danger">
        <div className="text-sm text-fg-muted">Overdue</div>
        <div className="text-2xl font-bold text-danger">{view.overdueObligations}</div>
      </Card>
      <Card className="p-4 border-l-4 border-l-warning">
        <div className="text-sm text-fg-muted">Due this week</div>
        <div className="text-2xl font-bold text-warning">{view.dueThisWeek}</div>
      </Card>
      <Card className="p-4 border-l-4 border-l-success">
        <div className="text-sm text-fg-muted">Completed</div>
        <div className="text-2xl font-bold text-success">{view.completedObligations}</div>
      </Card>
    </div>
  );
}

function RecentActivity({ activities }: { activities: any[] }) {
  return (
    <Card>
      <h3 className="text-sm font-medium text-fg mb-4">Recent activity</h3>
      <div className="flex flex-col gap-3">
        {activities.length === 0 ? (
          <EmptyState
            title="No recent activity"
            description="Activity will appear here as you use the platform."
          />
        ) : (
          activities.map((activity) => (
            <div
              key={activity.id}
              className="flex items-start gap-3 py-2 border-b border-line last:border-0"
            >
              <div className="mt-1">
                <Icon name={activity.icon || "activity"} className="h-4 w-4 text-fg-muted" />
              </div>
              <div className="flex-1">
                <p className="text-sm text-fg">{activity.description}</p>
                <p className="text-xs text-fg-muted">
                  {new Date(activity.timestamp).toLocaleString()}
                </p>
              </div>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

function UrgentActions({ actions }: { actions: any[] }) {
  return (
    <Card>
      <h3 className="text-sm font-medium text-fg mb-4">Urgent actions</h3>
      {actions.length === 0 ? (
        <EmptyState title="No urgent actions" description="Everything looks good!" />
      ) : (
        <div className="flex flex-col gap-3">
          {actions.map((action) => (
            <Link key={action.id} href={action.href}>
              <div className="flex items-center justify-between rounded-md border border-line p-3 hover:bg-muted">
                <div>
                  <p className="text-sm font-medium text-fg">{action.title}</p>
                  <p className="text-xs text-fg-muted">{action.description}</p>
                </div>
                <Badge tone="danger">{action.dueLabel}</Badge>
              </div>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

export function DashboardViewComponent({
  view,
  businessHref,
  obligationHref,
  href,
}: DashboardViewProps) {
  return (
    <div data-slot="dashboard" className="flex flex-col gap-6">
      <PageHeader title="Dashboard" description="Compliance overview and status" />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ObligationsSummary view={view} />
        </div>
        <div>
          <ComplianceScoreCard score={view.complianceScore} />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <RecentActivity activities={view.recentActivities} />
        <UrgentActions actions={view.urgentActions} />
      </div>

      {view.businesses.length > 0 && (
        <Card>
          <h3 className="text-sm font-medium text-fg mb-4">Your businesses</h3>
          <div className="flex flex-col gap-3">
            {view.businesses.map((business) => (
              <Link key={business.id} href={businessHref(business.id)}>
                <div className="flex items-center justify-between rounded-md border border-line p-4 hover:bg-muted">
                  <div>
                    <p className="font-medium text-fg">{business.name}</p>
                    <p className="text-xs text-fg-muted">
                      {business.type} · {business.complianceScore}% score
                    </p>
                  </div>
                  <Badge tone={business.status === "active" ? "success" : "warning"}>
                    {business.status}
                  </Badge>
                </div>
              </Link>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
