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
import { formatFileSize } from "@/features/evidence/model/evidence";
import type { EvidenceList, EvidenceItem } from "@/features/evidence/model/evidence";

export interface EvidenceViewProps {
  view: EvidenceList;
  onUpload?: () => void;
  onDelete?: (id: string) => void;
  onPreview?: (item: EvidenceItem) => void;
}

export function EvidenceViewComponent({ view, onUpload, onDelete, onPreview }: EvidenceViewProps) {
  const [progress, setProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [filter, setFilter] = useState<string>("all");

  const filtered = useMemo(() => {
    if (filter === "all") return view.items;
    return view.items.filter((i) => i.status === filter);
  }, [view.items, filter]);

  const handleUpload = () => {
    if (!onUpload) return;
    setUploading(true);
    setProgress(0);
    const interval = setInterval(() => {
      setProgress((p) => {
        if (p >= 100) {
          clearInterval(interval);
          setUploading(false);
          return 100;
        }
        return p + 20;
      });
    }, 200);
  };

  return (
    <div data-slot="evidence" className="flex flex-col gap-6">
      <PageHeader
        title={view.obligationName}
        description="Manage evidence files for this obligation"
        actions={
          onUpload ? (
            <Button variant="primary" onClick={handleUpload} disabled={uploading}>
              Upload evidence
            </Button>
          ) : null
        }
      />

      {uploading && (
        <Card className="p-4">
          <ProgressBar value={progress} />
          <p className="text-sm text-fg-muted mt-2">Uploading... {progress}%</p>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Total files</p>
          <p className="text-2xl font-semibold text-fg">{view.items.length}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Accepted</p>
          <p className="text-2xl font-semibold text-success">
            {view.items.filter((i) => i.status === "accepted").length}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-fg-muted">Rejected</p>
          <p className="text-2xl font-semibold text-danger">
            {view.items.filter((i) => i.status === "rejected").length}
          </p>
        </Card>
      </div>

      <Tabs
        tabs={[
          { value: "all", label: "All files" },
          { value: "submitted", label: "Submitted" },
          { value: "accepted", label: "Accepted" },
          { value: "rejected", label: "Rejected" },
        ]}
        value={filter}
        onChange={(v) => setFilter(v)}
      />

      {filtered.length === 0 ? (
        <Card>
          <EmptyState
            title="No evidence files"
            description="Upload files to provide evidence for this obligation."
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Size</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Uploaded by</TableHead>
                <TableHead>Uploaded</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium text-fg">{item.fileName}</TableCell>
                  <TableCell className="text-fg-muted">{formatFileSize(item.sizeBytes)}</TableCell>
                  <TableCell>
                    <Badge
                      tone={
                        item.status === "accepted"
                          ? "success"
                          : item.status === "rejected"
                            ? "danger"
                            : "info"
                      }
                    >
                      {item.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-fg-muted">{item.uploadedBy}</TableCell>
                  <TableCell className="text-fg-muted">
                    {new Date(item.uploadedAt).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button variant="ghost" size="sm" onClick={() => onPreview?.(item)}>
                        Preview
                      </Button>
                      {item.status === "submitted" && onDelete && (
                        <Button variant="ghost" size="sm" onClick={() => onDelete(item.id)}>
                          Delete
                        </Button>
                      )}
                    </div>
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
