"use client";

import { useState } from "react";
import { Button, Card, PageHeader, ProgressBar } from "@compliancewatch/ui";

export interface BackfillJob {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  startedAt: string | null;
  completedAt: string | null;
}

export interface AdminBackfillView {
  jobs: BackfillJob[];
  totalCount: number;
  runningCount: number;
}

export function emptyAdminBackfill(): AdminBackfillView {
  return { jobs: [], totalCount: 0, runningCount: 0 };
}

export function AdminBackfillViewComponent({ view }: { view: AdminBackfillView }) {
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);

  const startBackfill = () => {
    setRunning(true);
    setProgress(0);
    const interval = setInterval(() => {
      setProgress((p) => {
        if (p >= 100) {
          clearInterval(interval);
          setRunning(false);
          return 100;
        }
        return p + 10;
      });
    }, 300);
  };

  return (
    <div data-slot="admin-backfill" className="flex flex-col gap-6">
      <PageHeader title="Backfill" description="Rebuild derived data from source records" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
          <p className="text-2xl font-semibold text-success">
            {view.jobs.filter((j) => j.status === "completed").length}
          </p>
        </Card>
      </div>

      <Card className="p-6">
        <h3 className="text-sm font-medium text-fg mb-4">Quick backfill</h3>
        <p className="text-sm text-fg-muted mb-4">
          Trigger a full rebuild of derived data from source records. This may take several minutes.
        </p>
        {running ? (
          <div className="flex flex-col gap-2">
            <ProgressBar value={progress} />
            <span className="text-sm text-fg-muted">Processing... {progress}%</span>
          </div>
        ) : (
          <Button variant="primary" onClick={startBackfill}>
            Start backfill
          </Button>
        )}
      </Card>

      {view.jobs.length > 0 && (
        <div className="overflow-hidden rounded-md border border-line">
          <table className="w-full">
            <thead>
              <tr className="border-b border-line">
                <th className="px-4 py-3 text-left text-sm font-medium text-fg-muted">Job</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-fg-muted">Status</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-fg-muted">Progress</th>
              </tr>
            </thead>
            <tbody>
              {view.jobs.map((job) => (
                <tr key={job.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-3 text-sm text-fg">{job.name}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex rounded-full px-2 py-1 text-xs font-medium bg-muted text-fg-muted">
                      {job.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="h-2 w-24 rounded-full bg-muted">
                        <div
                          className="h-2 rounded-full bg-primary"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-fg-muted">{job.progress}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
