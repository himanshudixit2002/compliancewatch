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
  Tabs,
} from "@compliancewatch/ui";
import { qaPriorityTone } from "../model/qa-triage";
import type { AdminQaTriageView } from "../model/qa-triage";

export interface AdminQaTriageViewProps {
  view: AdminQaTriageView;
}

function QaRow({ item }: { item: AdminQaTriageView["items"][number] }) {
  return (
    <TableRow>
      <TableCell className="font-medium text-fg">{item.title}</TableCell>
      <TableCell>
        <Badge tone="info">{item.category}</Badge>
      </TableCell>
      <TableCell>
        <Badge tone={qaPriorityTone(item.priority)}>{item.priority}</Badge>
      </TableCell>
      <TableCell>
        <Badge tone="info">{item.status}</Badge>
      </TableCell>
      <TableCell className="text-fg-muted">{item.assignee}</TableCell>
      <TableCell className="text-fg-muted">{new Date(item.createdAt).toLocaleString()}</TableCell>
      <TableCell>
        <Button variant="ghost" size="sm">Review</Button>
      </TableCell>
    </TableRow>
  );
}

export function AdminQaTriageViewComponent({ view }: AdminQaTriageViewProps) {
  const openCount = useMemo(() => view.items.filter((i) => i.status === "open").length, [view.items]);

  return (
    <div data-slot="admin-qa-triage" className="flex flex-col gap-6">
      <PageHeader title="QA triage" description="Quality assurance workflow" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total items</p>
          <p className="text-2xl font-semibold text-fg">{view.totalCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Open</p>
          <p className="text-2xl font-semibold text-warning">{openCount}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Closed</p>
          <p className="text-2xl font-semibold text-success">{view.items.filter((i) => i.status === "closed").length}</p>
        </Card>
      </div>

      <Input
        placeholder="Search..."
        onChange={() => {}}
      />

      {view.items.length === 0 ? (
        <Card>
          <EmptyState
            title="No QA items"
            description="Quality items will appear here for review."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Assignee</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.items.map((item) => (
                <QaRow key={item.id} item={item} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}