"use client";

import { useMemo } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { evalScoreTone } from "../model/evals";
import type { AdminEvalsView } from "../model/evals";

export interface AdminEvalsViewProps {
  view: AdminEvalsView;
}

function EvalRow({ run }: { run: AdminEvalsView["runs"][number] }) {
  return (
    <TableRow>
      <TableCell className="font-medium text-fg">{run.name}</TableCell>
      <TableCell>
        <Badge tone="info">{run.model}</Badge>
      </TableCell>
      <TableCell>
        <Badge tone={evalScoreTone(run.score)}>{run.status}</Badge>
      </TableCell>
      <TableCell className="text-fg-muted">
        {run.score !== null ? `${Math.round(run.score * 100)}%` : "—"}
      </TableCell>
      <TableCell className="text-fg-muted">{new Date(run.createdAt).toLocaleString()}</TableCell>
      <TableCell>
        <Button variant="ghost" size="sm">
          View
        </Button>
      </TableCell>
    </TableRow>
  );
}

export function AdminEvalsViewComponent({ view }: AdminEvalsViewProps) {
  const avgScore = useMemo(() => {
    const scored = view.runs.filter((r) => r.score !== null);
    if (scored.length === 0) return null;
    return scored.reduce((sum, r) => sum + (r.score ?? 0), 0) / scored.length;
  }, [view.runs]);

  return (
    <div data-slot="admin-evals" className="flex flex-col gap-6">
      <PageHeader title="LLM evaluations" description="Monitor and evaluate model performance" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total runs</p>
          <p className="text-2xl font-semibold text-fg">{view.totalCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Avg score</p>
          <p className="text-2xl font-semibold">
            {avgScore !== null ? `${Math.round(avgScore * 100)}%` : "—"}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Passed</p>
          <p className="text-2xl font-semibold text-success">
            {view.runs.filter((r) => (r.score ?? 0) >= 0.8).length}
          </p>
        </Card>
      </div>

      {view.runs.length === 0 ? (
        <Card>
          <EmptyState
            title="No evaluation runs"
            description="Run evaluations to measure model performance."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.runs.map((run) => (
                <EvalRow key={run.id} run={run} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
