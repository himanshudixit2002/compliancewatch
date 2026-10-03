"use client";

import { useMemo } from "react";
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
} from "@compliancewatch/ui";

export interface QualityMetric {
  id: string;
  name: string;
  value: number;
  target: number;
  unit: string;
  status: "healthy" | "warning" | "critical";
}

export interface SystemQualityView {
  metrics: QualityMetric[];
  overallScore: number;
}

export function emptySystemQuality(): SystemQualityView {
  return { metrics: [], overallScore: 0 };
}

export function SystemQualityViewComponent({ view }: { view: SystemQualityView }) {
  const healthyCount = useMemo(() => view.metrics.filter((m) => m.status === "healthy").length, [view.metrics]);

  return (
    <div data-slot="system-quality" className="flex flex-col gap-6">
      <PageHeader title="System quality" description="Monitor system health and performance" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Overall score</p>
          <p className="text-2xl font-semibold">{view.overallScore > 0 ? `${view.overallScore}%` : "—"}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Healthy metrics</p>
          <p className="text-2xl font-semibold text-success">{healthyCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total metrics</p>
          <p className="text-2xl font-semibold text-fg">{view.metrics.length}</p>
        </Card>
      </div>

      {view.metrics.length === 0 ? (
        <Card>
          <EmptyState
            title="No metrics"
            description="System quality metrics will appear here."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Metric</TableHead>
                <TableHead>Current</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.metrics.map((metric) => (
                <TableRow key={metric.id}>
                  <TableCell className="font-medium text-fg">{metric.name}</TableCell>
                  <TableCell className="text-fg">{metric.value} {metric.unit}</TableCell>
                  <TableCell className="text-fg-muted">{metric.target} {metric.unit}</TableCell>
                  <TableCell>
                    <Badge tone={metric.status === "healthy" ? "success" : metric.status === "warning" ? "warning" : "danger"}>
                      {metric.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}