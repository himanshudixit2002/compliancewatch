"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  EmptyState,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { BadgeTone } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import type {
  DataRight,
  DataRightStatus,
  DataRightType,
  DataRightsView,
} from "../model/data-rights";

export interface DataRightsViewProps {
  title: string;
  view: DataRightsView;
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  onRequest?: (type: DataRightType) => void;
}

const STATUS_TONE: Readonly<Record<DataRightStatus, BadgeTone>> = {
  pending: "warning",
  processing: "info",
  fulfilled: "success",
  rejected: "danger",
};

const TYPE_LABEL: Readonly<Record<DataRightType, string>> = {
  access: "Data access",
  rectification: "Rectification",
  erasure: "Erasure",
  portability: "Portability",
};

const REQUEST_TYPES: readonly DataRightType[] = [
  "access",
  "rectification",
  "erasure",
  "portability",
];

function StatusBadge({ status }: { status: DataRightStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{status}</Badge>;
}

function RightRow({ right }: { right: DataRight }) {
  return (
    <TableRow data-right-id={right.id}>
      <TableCell className="font-medium text-fg">{TYPE_LABEL[right.type]}</TableCell>
      <TableCell>
        <StatusBadge status={right.status} />
      </TableCell>
      <TableCell className="text-fg-muted whitespace-nowrap">
        {formatDate(right.requestedAt)}
      </TableCell>
      <TableCell className="text-fg-muted whitespace-nowrap">
        {right.resolvedAt ? formatDate(right.resolvedAt) : "—"}
      </TableCell>
      <TableCell className="max-w-xs truncate">{right.description}</TableCell>
    </TableRow>
  );
}

/**
 * The data rights settings page: the settings header, a button to request a new right, and a table
 * of existing requests with their type, status, dates and description, newest first.
 */
export function DataRightsView({ title, view, crumbs, tabs, onRequest }: DataRightsViewProps) {
  return (
    <div data-slot="data-rights" className="flex flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("settings.about.owner.settings.data_rights")}
        crumbs={crumbs}
        tabs={tabs}
      />
      {view.rights.length === 0 ? (
        <EmptyState
          title="No data rights requests"
          body="You have not submitted any data rights requests yet."
          action={<RequestDialog onRequest={onRequest} />}
        />
      ) : (
        <>
          <div className="flex justify-end">
            <RequestDialog onRequest={onRequest} trigger={<Button>Request new right</Button>} />
          </div>
          <Table>
            <TableCaption className="text-left text-sm text-fg-muted">
              {view.totalCount} {view.totalCount === 1 ? "request" : "requests"}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Requested</TableHead>
                <TableHead>Resolved</TableHead>
                <TableHead>Description</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.rights.map((right) => (
                <RightRow key={right.id} right={right} />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}

function RequestDialog({
  onRequest,
  trigger,
}: {
  onRequest?: (type: DataRightType) => void;
  trigger?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger ? <DialogTrigger asChild>{trigger}</DialogTrigger> : null}
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request data right</DialogTitle>
          <DialogDescription>
            Choose the type of data right you want to request under data protection law.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          {REQUEST_TYPES.map((type) => (
            <Button
              key={type}
              variant="secondary"
              className="justify-start"
              onClick={() => {
                onRequest?.(type);
                setOpen(false);
              }}
            >
              {TYPE_LABEL[type]}
            </Button>
          ))}
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
