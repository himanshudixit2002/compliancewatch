"use client";

import { useState, useMemo } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  PageHeader,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
} from "@compliancewatch/ui";
import {
  actionCategory,
  actionLabel,
  type AuditView,
} from "../model/audit";

export interface AuditViewProps {
  view: AuditView;
}

function AuditRow({ entry }: { entry: AuditView["entries"][number] }) {
  const category = actionCategory(entry.action);
  return (
    <TableRow>
      <TableCell className="text-fg-muted whitespace-nowrap">
        {new Date(entry.createdAt).toLocaleString()}
      </TableCell>
      <TableCell className="font-medium text-fg">{entry.actorName}</TableCell>
      <TableCell>
        <Badge tone="info">{category}</Badge>
      </TableCell>
      <TableCell>
        <span className="text-fg">{entry.action}</span>
      </TableCell>
      <TableCell className="text-fg-muted">
        {entry.targetType}: {entry.targetId}
      </TableCell>
      <TableCell className="text-fg-muted max-w-xs truncate">
        {entry.changes}
      </TableCell>
      <TableCell className="text-fg-muted font-mono text-xs">
        {entry.ipAddress}
      </TableCell>
    </TableRow>
  );
}

export function AuditViewComponent({ view }: AuditViewProps) {
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [actorSearch, setActorSearch] = useState("");

  const categories = useMemo(() => {
    const cats = new Set(view.entries.map((e) => actionCategory(e.action)));
    return ["all", ...Array.from(cats)];
  }, [view.entries]);

  const filtered = useMemo(() => {
    let items = view.entries;
    if (categoryFilter !== "all") {
      items = items.filter((e) => actionCategory(e.action) === categoryFilter);
    }
    if (actorSearch) {
      const q = actorSearch.toLowerCase();
      items = items.filter((e) => e.actorName.toLowerCase().includes(q));
    }
    return items;
  }, [view.entries, categoryFilter, actorSearch]);

  const tabs = categories.map((cat) => ({
    value: cat,
    label: cat === "all" ? "All" : cat.charAt(0).toUpperCase() + cat.slice(1),
  }));

  return (
    <div data-slot="admin-audit" className="flex flex-col gap-6">
      <PageHeader title="Audit log" description="Track all system activities" />

      <Card className="p-4">
        <div className="flex flex-col gap-4 sm:flex-row">
          <div className="flex flex-1 flex-col gap-1">
            <label className="text-sm font-medium text-fg">From</label>
            <Input type="date" value={view.dateRange.from} onChange={() => {}} />
          </div>
          <div className="flex flex-1 flex-col gap-1">
            <label className="text-sm font-medium text-fg">To</label>
            <Input type="date" value={view.dateRange.to} onChange={() => {}} />
          </div>
        </div>
      </Card>

      <Input
        placeholder="Search by actor name..."
        value={actorSearch}
        onChange={(e) => setActorSearch(e.target.value)}
      />

      <Tabs tabs={tabs} value={categoryFilter} onChange={(v) => setCategoryFilter(v)} />

      {filtered.length === 0 ? (
        <Card>
          <EmptyState
            title="No audit entries found"
            description="Audit log entries will appear here as system actions occur."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Timestamp</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Changes</TableHead>
                <TableHead>IP Address</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((entry) => (
                <AuditRow key={entry.id} entry={entry} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}