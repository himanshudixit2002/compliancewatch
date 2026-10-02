"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  Icon,
  PageHeader,
  SearchInput,
  Select,
  StatCard,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
} from "@compliancewatch/ui";

export interface CaDashboardView {
  clients: CaClient[];
  totalClients: number;
  activeEngagements: number;
  pendingReviews: number;
  totalRevenue: number;
  completionRate: number;
  filter: string;
  sort: string;
}

export interface CaClient {
  id: string;
  name: string;
  type: string;
  industry: string;
  engagementStatus: "active" | "inactive" | "pending";
  complianceScore: number;
  obligationsDue: number;
  obligationsOverdue: number;
  lastUpdated: string;
  assignedTo: string;
}

function StatCards({ view }: { view: CaDashboardView }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
      <StatCard label="Total clients" value={view.totalClients} tone="info" />
      <StatCard label="Active engagements" value={view.activeEngagements} tone="success" />
      <StatCard label="Pending reviews" value={view.pendingReviews} tone="warning" />
      <StatCard label="Completion rate" value={`${view.completionRate}%`} tone="info" />
      <StatCard label="Compliance score" value={`${Math.round(view.clients.reduce((a, c) => a + c.complianceScore, 0) / Math.max(view.clients.length, 1))}%`} tone="neutral" />
    </div>
  );
}

function ClientsTable({ clients }: { clients: CaClient[] }) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const filtered = clients.filter((c) => {
    if (search && !c.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (statusFilter !== "all" && c.engagementStatus !== statusFilter) return false;
    return true;
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row">
        <SearchInput
          placeholder="Search clients..."
          value={search}
          onChange={setSearch}
          className="flex-1"
        />
        <Select
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: "all", label: "All statuses" },
            { value: "active", label: "Active" },
            { value: "inactive", label: "Inactive" },
            { value: "pending", label: "Pending" },
          ]}
          className="w-full sm:w-48"
        />
      </div>

      {filtered.length === 0 ? (
        <Card>
          <div className="py-12 text-center">
            <Icon name="users" className="mx-auto h-8 w-8 text-fg-muted mb-2" />
            <p className="text-sm text-fg-muted">No clients found matching your filters.</p>
          </div>
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Client</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Industry</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>Overdue</TableHead>
                <TableHead>Last updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((client) => (
                <TableRow key={client.id}>
                  <TableCell className="font-medium text-fg">{client.name}</TableCell>
                  <TableCell>{client.type}</TableCell>
                  <TableCell>{client.industry}</TableCell>
                  <TableCell>
                    <Badge tone={client.engagementStatus === "active" ? "success" : client.engagementStatus === "pending" ? "warning" : "neutral"}>
                      {client.engagementStatus}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="h-2 w-16 rounded-full bg-muted">
                        <div
                          className="h-2 rounded-full bg-success"
                          style={{ width: `${client.complianceScore}%` }}
                        />
                      </div>
                      <span className="text-xs text-fg-muted">{client.complianceScore}%</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge tone={client.obligationsOverdue > 0 ? "danger" : "success"}>
                      {client.obligationsOverdue}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-fg-muted">{new Date(client.lastUpdated).toLocaleDateString()}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export function CaDashboardViewComponent({ view }: { view: CaDashboardView }) {
  const [tab, setTab] = useState("all");

  return (
    <div data-slot="ca-dashboard" className="flex flex-col gap-6">
      <PageHeader
        title="CA Dashboard"
        description="Manage your client engagements and compliance oversight"
      />

      <StatCards view={view} />

      <Tabs
        tabs={[
          { value: "all", label: "All clients" },
          { value: "active", label: "Active" },
          { value: "inactive", label: "Inactive" },
          { value: "pending", label: "Pending" },
        ]}
        value={tab}
        onChange={setTab}
      />

      <ClientsTable clients={tab === "all" ? view.clients : view.clients.filter((c) => c.engagementStatus === tab)} />
    </div>
  );
}
