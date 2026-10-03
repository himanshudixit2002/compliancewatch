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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
} from "@compliancewatch/ui";
import {
  pipelineStatusTone,
  type PipelineView,
} from "../model/pipeline";

export interface PipelineViewProps {
  view: PipelineView;
  onRetry?: (taskId: string) => void;
}

function PipelineRow({ task, onRetry }: { task: PipelineView["tasks"][number]; onRetry?: (id: string) => void }) {
  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-col">
          <span className="font-medium text-fg">{task.name}</span>
          <span className="text-xs text-fg-muted">{task.type}</span>
        </div>
      </TableCell>
      <TableCell>
        <Badge tone={pipelineStatusTone(task.status)}>{task.status}</Badge>
      </TableCell>
      <TableCell>
        <div className="w-32">
          <ProgressBar value={task.progress} />
          <span className="text-xs text-fg-muted">{task.progress}%</span>
        </div>
      </TableCell>
      <TableCell className="text-fg-muted text-sm">{task.duration || "—"}</TableCell>
      <TableCell className="text-fg-muted text-sm">
        {task.startedAt ? new Date(task.startedAt).toLocaleString() : "—"}
      </TableCell>
      <TableCell>
        {task.status === "failed" && (
          <Button variant="ghost" size="sm" onClick={() => onRetry?.(task.id)}>
            Retry
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

export function PipelineViewComponent({ view, onRetry }: PipelineViewProps) {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<string>("all");

  const filtered = useMemo(() => {
    let items = view.tasks;
    if (tab !== "all") {
      items = items.filter((t) => t.status === tab);
    }
    if (search) {
      const q = search.toLowerCase();
      items = items.filter((t) => t.name.toLowerCase().includes(q) || t.type.toLowerCase().includes(q));
    }
    return items;
  }, [view.tasks, tab, search]);

  return (
    <div data-slot="admin-pipeline" className="flex flex-col gap-6">
      <PageHeader title="Pipeline" description="Background job monitoring" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total jobs</p>
          <p className="text-2xl font-semibold text-fg">{view.totalCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Running</p>
          <p className="text-2xl font-semibold text-warning">{view.runningCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Completed</p>
          <p className="text-2xl font-semibold text-success">{view.completedCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Failed</p>
          <p className="text-2xl font-semibold text-danger">{view.failedCount}</p>
        </Card>
      </div>

      <Tabs
        tabs={[
          { value: "all", label: "All" },
          { value: "running", label: "Running" },
          { value: "completed", label: "Completed" },
          { value: "failed", label: "Failed" },
        ]}
        value={tab}
        onChange={(v) => setTab(v)}
      />

      <Input
        placeholder="Search jobs..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {filtered.length === 0 ? (
        <Card>
          <EmptyState
            title="No pipeline jobs"
            description="Background jobs will appear here."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((task) => (
                <PipelineRow key={task.id} task={task} onRetry={onRetry} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}