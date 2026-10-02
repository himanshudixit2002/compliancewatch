"use client";

import { useState } from "react";
import { Badge, Banner, Button, Card, PageHeader, SearchInput, Tabs, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, EmptyState, Icon } from "@compliancewatch/ui";
import type { RiskView } from "../model/risk";
import { riskLevelLabel, formatRiskDate } from "../model/risk";

export interface RiskViewProps {
  view: RiskView;
  businessId: string;
  href: (riskId: string) => string;
}

const TABS = [
  { value: "all", label: "All risks" },
  { value: "active", label: "Active" },
  { value: "mitigated", label: "Mitigated" },
  { value: "closed", label: "Closed" },
];

function StatCards({ view }: { view: RiskView }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Card className="p-4">
        <div className="text-sm text-fg-muted">Total risks</div>
        <div className="text-2xl font-bold text-fg">{view.totalCount}</div>
      </Card>
      <Card className="p-4 border-l-4 border-l-danger">
        <div className="text-sm text-fg-muted">High severity</div>
        <div className="text-2xl font-bold text-danger">{view.highCount}</div>
      </Card>
      <Card className="p-4 border-l-4 border-l-warning">
        <div className="text-sm text-fg-muted">Medium severity</div>
        <div className="text-2xl font-bold text-warning">{view.mediumCount}</div>
      </Card>
      <Card className="p-4 border-l-4 border-l-success">
        <div className="text-sm text-fg-muted">Mitigated</div>
        <div className="text-2xl font-bold text-success">{view.mitigatedCount}</div>
      </Card>
    </div>
  );
}

function RisksTable({ risks, href }: { risks: any[]; href: (riskId: string) => string }) {
  const [search, setSearch] = useState("");

  const filtered = risks.filter((r) => {
    if (search && !r.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="flex flex-col gap-4">
      <SearchInput
        placeholder="Search risks..."
        value={search}
        onChange={setSearch}
        className="w-full sm:max-w-sm"
      />
      {filtered.length === 0 ? (
        <EmptyState icon={<Icon name="shield-check" className="h-8 w-8 text-fg-muted" />} title="No risks found" description="Your compliance posture looks good." />
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Risk</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Likelihood</TableHead>
                <TableHead>Identified</TableHead>
                <TableHead>Owner</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((risk) => (
                <TableRow key={risk.id}>
                  <TableCell className="font-medium text-fg">
                    <a href={href(risk.id)} className="hover:underline">{risk.title}</a>
                  </TableCell>
                  <TableCell>
                    <Badge tone={risk.severity === "high" ? "danger" : risk.severity === "medium" ? "warning" : "info"}>
                      {risk.severity}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge tone={risk.status === "active" ? "danger" : risk.status === "mitigated" ? "success" : "neutral"}>
                      {risk.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{risk.likelihood}%</TableCell>
                  <TableCell>{formatRiskDate(risk.identifiedAt)}</TableCell>
                  <TableCell>{risk.owner}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export function RiskViewComponent({ view, businessId, href }: RiskViewProps) {
  const [tab, setTab] = useState("all");
  const filtered = tab === "all" ? view.risks : view.risks.filter((r) => r.status === tab);

  return (
    <div data-slot="risk" className="flex flex-col gap-6">
      <PageHeader title="Risk register" description="Track and manage regulatory risks" />
      <StatCards view={view} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      <RisksTable risks={filtered} href={href} />
    </div>
  );
}
