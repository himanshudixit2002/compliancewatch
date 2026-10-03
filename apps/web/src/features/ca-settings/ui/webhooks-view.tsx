"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { t } from "@/shared/i18n";
import type { Webhook } from "../model/settings";
import { webhookEventLabel } from "../model/settings";

export interface WebhooksViewProps {
  title: string;
  webhooks: readonly Webhook[];
  onAddWebhook?: (webhook: {
    url: string;
    events: string[];
    active: boolean;
  }) => void | Promise<void>;
  onToggleActive?: (id: string, active: boolean) => void | Promise<void>;
}

const COMMON_EVENTS: { value: string; label: string }[] = [
  { value: "obligation.created", label: t("caSettings.webhook.event.obligation_created") },
  { value: "obligation.updated", label: t("caSettings.webhook.event.obligation_updated") },
  { value: "obligation.completed", label: t("caSettings.webhook.event.obligation_completed") },
  { value: "evidence.submitted", label: t("caSettings.webhook.event.evidence_submitted") },
  { value: "review.pending", label: t("caSettings.webhook.event.review_pending") },
  { value: "review.completed", label: t("caSettings.webhook.event.review_completed") },
  { value: "digest.sent", label: t("caSettings.webhook.event.digest_sent") },
];

interface AddWebhookFormProps {
  onSubmit: (webhook: { url: string; events: string[]; active: boolean }) => void | Promise<void>;
}

function AddWebhookForm({ onSubmit }: AddWebhookFormProps) {
  const [url, setUrl] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);
  const [active, setActive] = useState(true);
  const [saving, setSaving] = useState(false);

  const toggleEvent = (value: string) => {
    setSelectedEvents((current) =>
      current.includes(value) ? current.filter((e) => e !== value) : [...current, value],
    );
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!url.trim() || selectedEvents.length === 0) return;
    setSaving(true);
    try {
      await onSubmit({ url: url.trim(), events: selectedEvents, active });
      setUrl("");
      setSelectedEvents([]);
      setActive(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <SheetHeader>
        <SheetTitle>{t("caSettings.webhook.addTitle")}</SheetTitle>
        <SheetDescription>{t("caSettings.webhook.addDescription")}</SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-4">
        <Field id="webhook-url" label={t("caSettings.webhook.url")} required>
          <Input
            id="webhook-url"
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder={t("caSettings.webhook.urlPlaceholder")}
            required
            maxLength={2048}
          />
        </Field>
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-fg">{t("caSettings.webhook.events")}</span>
          <div className="flex flex-col gap-2">
            {COMMON_EVENTS.map((option) => {
              const checked = selectedEvents.includes(option.value);
              return (
                <label
                  key={option.value}
                  className="flex items-center gap-2 rounded-md border border-line p-2 hover:bg-surface-muted"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleEvent(option.value)}
                    className="h-4 w-4 rounded border-line"
                  />
                  <span className="text-sm text-fg">{option.label}</span>
                </label>
              );
            })}
          </div>
          <p className="text-xs text-fg-muted">
            {t("caSettings.webhook.eventsHelp", { count: selectedEvents.length })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            id="webhook-active"
            type="checkbox"
            checked={active}
            onChange={(event) => setActive(event.target.checked)}
            className="h-4 w-4 rounded border-line text-primary focus:ring-focus/50"
          />
          <label htmlFor="webhook-active" className="text-sm font-medium text-fg">
            {t("caSettings.webhook.active")}
          </label>
        </div>
      </div>
      <SheetFooter>
        <Button type="submit" disabled={saving || !url.trim() || selectedEvents.length === 0}>
          {saving ? t("caSettings.webhook.adding") : t("caSettings.webhook.add")}
        </Button>
        <SheetClose asChild>
          <Button type="button" variant="ghost" disabled={saving}>
            {t("caSettings.cancel")}
          </Button>
        </SheetClose>
      </SheetFooter>
    </form>
  );
}

export function WebhooksView({ title, webhooks, onAddWebhook, onToggleActive }: WebhooksViewProps) {
  const [sheetOpen, setSheetOpen] = useState(false);

  const handleSubmit = async (webhook: { url: string; events: string[]; active: boolean }) => {
    if (!onAddWebhook) return;
    await onAddWebhook(webhook);
    setSheetOpen(false);
  };

  return (
    <div data-slot="ca-webhooks" className="flex max-w-3xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("caSettings.webhook.intro")}
        actions={
          onAddWebhook ? (
            <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
              <SheetTrigger asChild>
                <Button>{t("caSettings.webhook.add")}</Button>
              </SheetTrigger>
              <SheetContent>
                <AddWebhookForm onSubmit={handleSubmit} />
              </SheetContent>
            </Sheet>
          ) : null
        }
      />

      {webhooks.length === 0 ? (
        <Card>
          <EmptyState
            title={t("caSettings.webhook.emptyTitle")}
            description={t("caSettings.webhook.emptyDescription")}
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("caSettings.webhook.url")}</TableHead>
                <TableHead>{t("caSettings.webhook.events")}</TableHead>
                <TableHead>{t("caSettings.webhook.created")}</TableHead>
                <TableHead>{t("caSettings.webhook.lastTriggered")}</TableHead>
                <TableHead>{t("caSettings.webhook.status")}</TableHead>
                <TableHead aria-label={t("caSettings.actions")} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {webhooks.map((webhook) => (
                <TableRow key={webhook.id}>
                  <TableCell>
                    <div className="flex max-w-xs flex-col gap-1">
                      <a
                        href={webhook.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium text-fg hover:underline"
                      >
                        {webhook.url}
                      </a>
                      <code className="text-xs text-fg-muted">{webhook.id}</code>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {webhook.events.slice(0, 2).map((event) => (
                        <Badge key={event} tone="neutral" variant="subtle">
                          {webhookEventLabel(event)}
                        </Badge>
                      ))}
                      {webhook.events.length > 2 && (
                        <Badge tone="neutral" variant="subtle">
                          +{webhook.events.length - 2}
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm text-fg">{formatDate(webhook.createdAt)}</span>
                  </TableCell>
                  <TableCell>
                    {webhook.lastTriggered ? (
                      <span className="text-sm text-fg">
                        {formatDateTime(webhook.lastTriggered)}
                      </span>
                    ) : (
                      <span className="text-sm text-fg-muted">{t("caSettings.never")}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge tone={webhook.active ? "success" : "danger"}>
                      {webhook.active
                        ? t("caSettings.webhook.status.active")
                        : t("caSettings.webhook.status.disabled")}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {onToggleActive ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onToggleActive(webhook.id, !webhook.active)}
                      >
                        {webhook.active
                          ? t("caSettings.webhook.disable")
                          : t("caSettings.webhook.enable")}
                      </Button>
                    ) : null}
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
