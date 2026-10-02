"use client";

import { useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  PageHeader,
  SearchInput,
  StatCard,
  Table,
  Tabs,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { AdminNotificationsView } from "../model/admin-notifications";
import { channelLabel } from "../model/admin-notifications";

export interface AdminNotificationsViewProps {
  view: AdminNotificationsView;
}

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "digests", label: "Digests" },
  { value: "dispatch", label: "Dispatch log" },
  { value: "broadcasts", label: "Broadcasts" },
];

/** The admin notifications config: channel health, digest schedules, dispatch log and broadcasts. */
export function AdminNotificationsView({ view }: AdminNotificationsViewProps) {
  const [tab, setTab] = useState("overview");
  const [search, setSearch] = useState("");

  const overviewStats = [
    { label: "Total notifications", value: view.totalNotifications, tone: "info" as const },
    { label: "Delivery rate", value: `${view.deliveryRate}%`, tone: "success" as const },
    {
      label: "Channels active",
      value: view.channels.filter((c) => c.enabled).length,
      tone: "warning" as const,
    },
    { label: "Digests scheduled", value: view.digests.length, tone: "neutral" as const },
  ];

  return (
    <div data-slot="admin-notifications" className="flex flex-col gap-6">
      <PageHeader
        title="Notification management"
        description="Configure channels, digests and dispatch"
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {overviewStats.map((stat) => (
          <StatCard key={stat.label} {...stat} />
        ))}
      </div>

      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      {tab === "overview" && (
        <div className="flex flex-col gap-4">
          <h2 className="text-base font-semibold text-fg">Channels</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {view.channels.map((channel) => (
              <Card key={channel.kind} className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-fg">{channelLabel(channel.kind)}</span>
                  <Badge tone={channel.enabled ? "success" : "neutral"}>
                    {channel.enabled ? "Active" : "Inactive"}
                  </Badge>
                </div>
                <div className="flex flex-col gap-1 text-sm text-fg-muted">
                  <span>
                    Quota: {channel.quotaUsed} / {channel.quotaLimit}
                  </span>
                  <span>Last used: {new Date(channel.lastUsed).toLocaleDateString()}</span>
                </div>
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/admin/notifications/${channel.kind}`}>Configure</Link>
                </Button>
              </Card>
            ))}
          </div>
        </div>
      )}

      {tab === "dispatch" && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 sm:flex-row">
            <SearchInput
              placeholder="Search by recipient or ID..."
              value={search}
              onChange={setSearch}
              className="flex-1"
            />
          </div>
          <div className="overflow-hidden rounded-md border border-line">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Channel</TableHead>
                  <TableHead>Recipient</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Sent</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {view.dispatchLog.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell className="font-mono text-xs">{entry.id.slice(0, 8)}</TableCell>
                    <TableCell>{entry.kind}</TableCell>
                    <TableCell>{channelLabel(entry.channel)}</TableCell>
                    <TableCell>{entry.recipient}</TableCell>
                    <TableCell>
                      <Badge
                        tone={
                          entry.status === "delivered" || entry.status === "opened"
                            ? "success"
                            : entry.status === "failed" || entry.status === "bounced"
                              ? "danger"
                              : "info"
                        }
                      >
                        {entry.status}
                      </Badge>
                    </TableCell>
                    <TableCell>{new Date(entry.sentAt).toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  );
}
