"use client";

import { useMemo } from "react";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  ProgressBar,
  Tabs,
} from "@compliancewatch/ui";
import { StatCard } from "@/shared/ui/stat-card";
import { obligationStatusLabel, obligationStatusTone, isObligationOverdue, formatObligationDate } from "../model/obligations";
import type { Obligation } from "../model/obligations";

export interface ObligationDetailProps {
  obligation: Obligation;
  onStatusChange?: (status: string) => void;
  evidenceHref: string;
}

export function ObligationDetail({ obligation, onStatusChange, evidenceHref }: ObligationDetailProps) {
  const overdue = isObligationOverdue(obligation);
  const statusTone = obligationStatusTone(obligation.status);

  const progress = useMemo(() => {
    switch (obligation.status) {
      case "open": return 0;
      case "in_progress": return 50;
      case "done": return 100;
      case "waived": return 100;
      case "closed_not_applicable": return 100;
      default: return 0;
    }
  }, [obligation.status]);

  return (
    <div data-slot="obligation-detail" className="flex flex-col gap-6">
      <PageHeader
        title={obligation.title}
        description={obligation.description || "No description provided"}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Status" value={obligationStatusLabel(obligation.status)} tone={statusTone} />
        <StatCard label="Due date" value={formatObligationDate(obligation.dueAt)} tone={overdue ? "danger" : "neutral"} />
        <StatCard label="Evidence type" value={obligation.evidenceType} tone="info" />
        <StatCard label="Progress" value={`${progress}%`} tone={progress === 100 ? "success" : "info"} />
      </div>

      <Card className="p-6">
        <h3 className="text-sm font-medium text-fg mb-4">Completion progress</h3>
        <ProgressBar value={progress} />
      </Card>

      <Tabs
        tabs={[
          { value: "overview", label: "Overview" },
          { value: "evidence", label: "Evidence" },
          { value: "history", label: "History" },
        ]}
        value="overview"
        onChange={() => {}}
      />

      <Card className="p-6">
        <h3 className="text-sm font-medium text-fg mb-4">Obligation details</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-xs text-fg-muted">Decision ID</label>
            <p className="text-sm text-fg font-mono">{obligation.decisionId}</p>
          </div>
          <div>
            <label className="text-xs text-fg-muted">Rule Version ID</label>
            <p className="text-sm text-fg font-mono">{obligation.ruleVersionId}</p>
          </div>
          {obligation.periodLabel && (
            <div>
              <label className="text-xs text-fg-muted">Period</label>
              <p className="text-sm text-fg">{obligation.periodLabel}</p>
            </div>
          )}
          {obligation.closedAt && (
            <div>
              <label className="text-xs text-fg-muted">Closed at</label>
              <p className="text-sm text-fg">{formatObligationDate(obligation.closedAt)}</p>
            </div>
          )}
        </div>

        {obligation.steps.length > 0 && (
          <div className="mt-6">
            <label className="text-xs text-fg-muted mb-2 block">Required steps</label>
            <div className="flex flex-wrap gap-2">
              {obligation.steps.map((step) => (
                <Badge key={step} tone="neutral" variant="subtle">
                  {step}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </Card>

      <div className="flex flex-col gap-3 sm:flex-row">
        {obligation.status !== "done" && obligation.status !== "waived" && obligation.status !== "closed_not_applicable" && (
          <>
            <Button
              variant="primary"
              onClick={() => onStatusChange?.("in_progress")}
              disabled={obligation.status === "in_progress"}
            >
              {obligation.status === "open" ? "Start" : "Mark in progress"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => onStatusChange?.("done")}
            >
              Mark complete
            </Button>
          </>
        )}
        <Button variant="secondary" asChild>
          <Link href={evidenceHref}>Manage evidence</Link>
        </Button>
      </div>
    </div>
  );
}