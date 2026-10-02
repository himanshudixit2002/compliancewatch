"use client";

import type { Route } from "next";
import Link from "next/link";
import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Icon,
  PageHeader,
  SearchInput,
  Select,
} from "@compliancewatch/ui";
import type { ChangeView } from "@/features/changes/model/changes";
import {
  changeApplicabilityLabel,
  changeReviewLabel,
  formatEffectiveDate,
  changeSummary,
} from "@/features/changes/model/changes";

export interface ChangesViewProps {
  view: ChangeView;
  businessId: string;
  href: (changeId: string) => Route;
}

const APPLICABILITY_OPTIONS = [
  { value: "all", label: "All changes" },
  { value: "applies", label: "Applies to you" },
  { value: "pending", label: "Pending review" },
  { value: "does_not_apply", label: "Does not apply" },
  { value: "unknown", label: "Not yet evaluated" },
];

const REVIEW_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "published", label: "Published" },
  { value: "in_review", label: "In review" },
  { value: "draft", label: "Draft" },
  { value: "rejected", label: "Rejected" },
];

function ChangeCard({ change, businessId, href }: { change: any; businessId: string; href: (id: string) => Route }) {
  const applicabilityTone = change.applicability === "applies" ? "success" : change.applicability === "does_not_apply" ? "neutral" : change.applicability === "pending" ? "warning" : "info";
  const reviewTone = change.reviewStatus === "published" ? "success" : change.reviewStatus === "in_review" ? "warning" : change.reviewStatus === "rejected" ? "danger" : "neutral";

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-2 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-fg">{change.title}</span>
            <Badge tone={reviewTone}>{changeReviewLabel(change.reviewStatus)}</Badge>
            <Badge tone={applicabilityTone}>
              {changeApplicabilityLabel(change.applicability)}
            </Badge>
          </div>
          <p className="max-w-2xl text-sm text-fg-muted">{changeSummary(change.summary)}</p>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
            <span>From: {change.regulator}</span>
            <span>Effective: {formatEffectiveDate(change.effectiveDate)}</span>
            <span>Published: {formatEffectiveDate(change.publishedAt)}</span>
            {change.supersedes && <span>Supersedes: {change.supersedes}</span>}
            {change.confidence !== null && (
              <span>Confidence: {Math.round(change.confidence * 100)}%</span>
            )}
          </div>
          <div className="flex flex-wrap gap-1">
            {change.categories.map((cat: string) => (
              <span key={cat} className="rounded-full bg-line px-2 py-0.5 text-xs text-fg-muted">
                {cat}
              </span>
            ))}
          </div>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link href={href(change.id)}>View</Link>
        </Button>
      </div>
    </Card>
  );
}

/** The changes list for an owner or CA. */
export function ChangesView({ view, businessId, href }: ChangesViewProps) {
  const [search, setSearch] = useState("");
  const [applicabilityFilter, setApplicabilityFilter] = useState("all");
  const [reviewFilter, setReviewFilter] = useState("all");

  const filtered = view.changes.filter((change) => {
    if (search && !change.title.toLowerCase().includes(search.toLowerCase()) && !change.regulator.toLowerCase().includes(search.toLowerCase())) {
      return false;
    }
    if (applicabilityFilter !== "all" && change.applicability !== applicabilityFilter) {
      return false;
    }
    if (reviewFilter !== "all" && change.reviewStatus !== reviewFilter) {
      return false;
    }
    return true;
  });

  return (
    <div data-slot="changes" className="flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <PageHeader
            title="Regulatory changes"
            description={`${view.totalCount} changes · ${view.applicableCount} apply to you · ${view.pendingReviewCount} in review`}
          />
        </div>

        {view.totalCount === 0 ? (
          <EmptyState
            icon={<Icon name="file-text" className="h-8 w-8 text-fg-muted" />}
            title="No changes yet"
            description="Regulatory changes for your business will appear here once detected."
          />
        ) : (
          <>
            <div className="flex flex-col gap-3 sm:flex-row">
              <SearchInput
                placeholder="Search changes..."
                value={search}
                onChange={setSearch}
                className="flex-1"
              />
              <Select
                value={applicabilityFilter}
                onChange={setApplicabilityFilter}
                options={APPLICABILITY_OPTIONS}
                className="w-full sm:w-48"
              />
              <Select
                value={reviewFilter}
                onChange={setReviewFilter}
                options={REVIEW_OPTIONS}
                className="w-full sm:w-48"
              />
            </div>

            <div className="flex flex-col gap-3">
              {filtered.map((change) => (
                <ChangeCard key={change.id} change={change} businessId={businessId} href={href} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
