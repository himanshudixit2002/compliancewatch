"use client";

import { useState, useMemo } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  PageHeader,
  ProgressBar,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
} from "@compliancewatch/ui";
import type { ObligationView, Obligation } from "../model/obligations";
import {
  obligationStatusLabel,
  obligationStatusTone,
  isObligationOverdue,
  formatObligationDate,
} from "../model/obligations";

export interface ObligationsViewProps {
  view: ObligationView;
  businessId: string;
  href: (obligationId: string) => string;
}

const SORT_OPTIONS = [
  { value: "due", label: "Due date" },
  { value: "status", label: "Status" },
  { value: "created", label: "Created" },
  { value: "title", label: "Title" },
];

function ObligationRow({ obligation, href }: { obligation: Obligation; href: (id: string) => string }) {
  const overdue = isObligationOverdue(obligation);
  const statusTone = obligationStatusTone(obligation.status);

  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-col gap-1">
          <a href={href(obligation.id)} className="font-medium text-fg hover:underline">
            {obligation.title}
          </a>
          {obligation.description && (
            <span className="text-xs text-fg-muted line-clamp-1">{obligation.description}</span>
          )}
          {obligation.periodLabel && (
            <span className="text-xs text-fg-muted">
              Period: {obligation.periodLabel}
            </span>
          )}
        </div>
      </TableCell>
      <TableCell>
        <Badge tone={statusTone}>{obligationStatusLabel(obligation.status)}</Badge>
      </TableCell>
      <TableCell>
        <div className="flex flex-col gap-1">
          <span className={overdue ? "text-danger font-medium" : "text-fg"}>
            {formatObligationDate(obligation.dueAt)}
          </span>
          {overdue && (
            <span className="text-xs text-danger">Overdue</span>
          )}
        </div>
      </TableCell>
      <TableCell>
        <span className="text-sm text-fg-muted">{obligation.evidenceType}</span>
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {obligation.steps.slice(0, 3).map((step) => (
            <Badge key={step} tone="neutral" variant="subtle">
              {step}
            </Badge>
          ))}
          {obligation.steps.length > 3 && (
            <Badge tone="neutral" variant="subtle">
              +{obligation.steps.length - 3}
            </Badge>
          )}
        </div>
      </TableCell>
      <TableCell>
        <Button variant="ghost" size="sm" asChild>
          <a href={href(obligation.id)}>View</a>
        </Button>
      </TableCell>
    </TableRow>
  );
}

export function ObligationsViewComponent({ view, businessId, href }: ObligationsViewProps) {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<ObligationView["sort"]>(view.sort);

  const filtered = useMemo(() => {
    let items = view.obligations;

    if (view.filter !== "all") {
      items = items.filter((o) => o.status === view.filter);
    }

    if (search) {
      const q = search.toLowerCase();
      items = items.filter(
        (o) =>
          o.title.toLowerCase().includes(q) ||
          o.description?.toLowerCase().includes(q) ||
          o.evidenceType.toLowerCase().includes(q)
      );
    }

    items = [...items];
    switch (sort) {
      case "due":
        items.sort((a, b) => {
          if (!a.dueAt) return 1;
          if (!b.dueAt) return -1;
          return new Date(a.dueAt).getTime() - new Date(b.dueAt).getTime();
        });
        break;
      case "status":
        items.sort((a, b) => a.status.localeCompare(b.status));
        break;
      case "title":
        items.sort((a, b) => a.title.localeCompare(b.title));
        break;
    }

    return items;
  }, [view.obligations, view.filter, search, sort]);

  return (
    <div data-slot="obligations" className="flex flex-col gap-6">
      <PageHeader title="Obligations" description="Track regulatory obligations and deadlines" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total obligations</p>
          <p className="text-2xl font-semibold text-fg">{view.totalCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Open</p>
          <p className="text-2xl font-semibold text-fg">{view.openCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">In progress</p>
          <p className="text-2xl font-semibold text-warning">{view.inProgressCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Completed</p>
          <p className="text-2xl font-semibold text-success">{view.doneCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Overdue</p>
          <p className="text-2xl font-semibold text-danger">{view.overdueCount}</p>
        </Card>
      </div>

      <Tabs
        tabs={[
          { value: "all", label: "All" },
          { value: "open", label: "Open" },
          { value: "in_progress", label: "In progress" },
          { value: "done", label: "Done" },
          { value: "waived", label: "Waived" },
        ]}
        value={view.filter}
        onChange={() => {}}
      />

      <div className="flex flex-col gap-3 sm:flex-row">
        <Input
          placeholder="Search obligations..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1"
        />
        <Select value={sort} onChange={(v) => setSort(v as ObligationView["sort"])} options={SORT_OPTIONS} className="w-full sm:w-48" />
      </div>

      {filtered.length === 0 ? (
        <Card>
          <EmptyState
            title="No obligations found"
            description="Your regulatory obligations will appear here once assigned."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Obligation</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Due date</TableHead>
                <TableHead>Evidence type</TableHead>
                <TableHead>Steps</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((obligation) => (
                <ObligationRow key={obligation.id} obligation={obligation} href={href} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}