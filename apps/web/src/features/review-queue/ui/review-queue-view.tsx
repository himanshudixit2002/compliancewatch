"use client";

import { useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Icon,
  PageHeader,
  SearchInput,
  Select,
  StatCard,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
} from "@compliancewatch/ui";
import type { ReviewQueueView, ReviewItem } from "../model/review-queue";
import { reviewStatusLabel } from "../model/review-queue";

export interface ReviewQueueViewProps {
  view: ReviewQueueView;
  detailHref: (itemId: string) => Route;
  onApprove?: (itemId: string) => void;
  onReject?: (itemId: string) => void;
}

const FILTERS = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];

const TYPES = [
  { value: "all", label: "All types" },
  { value: "attribute_change", label: "Attribute change" },
  { value: "obligation_review", label: "Obligation" },
  { value: "evidence_review", label: "Evidence" },
  { value: "consent_change", label: "Consent" },
];

function ReviewItemRow({ item, href, onApprove, onReject }: { item: ReviewItem; href: (id: string) => Route; onApprove?: (id: string) => void; onReject?: (id: string) => void }) {
  return (
    <TableRow key={item.id}>
      <TableCell>
        <Link href={href(item.id)} className="font-medium text-fg hover:underline">
          {item.title}
        </Link>
        <div className="text-xs text-fg-muted">{item.description}</div>
      </TableCell>
      <TableCell>
        <Badge tone="info">{item.type}</Badge>
      </TableCell>
      <TableCell>
        <Badge tone={item.priority === "high" ? "danger" : item.priority === "medium" ? "warning" : "neutral"}>
          {item.priority}
        </Badge>
      </TableCell>
      <TableCell>{item.businessName}</TableCell>
      <TableCell className="text-sm">{item.submittedBy}</TableCell>
      <TableCell className="text-sm text-fg-muted">{new Date(item.submittedAt).toLocaleDateString()}</TableCell>
      <TableCell>
        <Badge tone={item.status === "approved" ? "success" : item.status === "rejected" ? "danger" : "warning"}>
          {reviewStatusLabel(item.status)}
        </Badge>
      </TableCell>
      {item.status === "pending" && (
        <TableCell>
          <div className="flex gap-2">
            <Button size="sm" variant="primary" onClick={() => onApprove?.(item.id)}>
              Approve
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onReject?.(item.id)}>
              Reject
            </Button>
          </div>
        </TableCell>
      )}
    </TableRow>
  );
}

export function ReviewQueueViewComponent({ view, detailHref, onApprove, onReject }: ReviewQueueViewProps) {
  const [filter, setFilter] = useState(view.filter);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");

  const filtered = view.items.filter((item) => {
    if (filter !== "all" && item.status !== filter) return false;
    if (typeFilter !== "all" && item.type !== typeFilter) return false;
    if (search && !item.title.toLowerCase().includes(search.toLowerCase()) && !item.businessName.toLowerCase().includes(search.toLowerCase())) {
      return false;
    }
    return true;
  });

  return (
    <div data-slot="review-queue" className="flex flex-col gap-6">
      <PageHeader title="Review queue" description="Review pending changes, attributes and obligations" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total items" value={view.totalCount} tone="info" />
        <StatCard label="Pending" value={view.pendingCount} tone="warning" />
        <StatCard label="Approved" value={view.approvedCount} tone="success" />
        <StatCard label="Rejected" value={view.rejectedCount} tone="danger" />
      </div>

      <div className="flex flex-col gap-3">
        <Tabs tabs={FILTERS} value={filter} onChange={setFilter} />
        <div className="flex flex-col gap-3 sm:flex-row">
          <SearchInput
            placeholder="Search by title or business..."
            value={search}
            onChange={setSearch}
            className="flex-1"
          />
          <Select value={typeFilter} onChange={setTypeFilter} options={TYPES} className="w-full sm:w-48" />
        </div>
      </div>

      {filtered.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Icon name="inbox" className="h-8 w-8 text-fg-muted" />}
            title="No items in queue"
            description="All reviews have been processed."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Business</TableHead>
                <TableHead>Submitted by</TableHead>
                <TableHead>Submitted</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => (
                <ReviewItemRow key={item.id} item={item} href={detailHref} onApprove={onApprove} onReject={onReject} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}