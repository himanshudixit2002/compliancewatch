"use client";

import { Badge, Button, EmptyState, Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@compliancewatch/ui";
import type { BadgeTone } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { SettingsHeader } from "@/shared/ui/settings-header";
import type { Recipient, RecipientsView } from "../model/recipients";

export interface RecipientsViewProps {
  title: string;
  view: RecipientsView;
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  onAdd?: () => void;
  onToggle?: (id: string, active: boolean) => void;
  onDelete?: (id: string) => void;
}

const CHANNEL_TONE: Readonly<Record<string, BadgeTone>> = {
  email: "info",
  whatsapp: "success",
  sms: "warning",
};

function ChannelBadges({ channels }: { channels: readonly string[] }) {
  if (channels.length === 0) {
    return <span className="text-fg-muted text-sm">{t("common.none")}</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {channels.map((channel) => (
        <Badge key={channel} tone={CHANNEL_TONE[channel] ?? "neutral"}>{channel}</Badge>
      ))}
    </div>
  );
}

function ActiveToggle({ id, active, onToggle }: { id: string; active: boolean; onToggle?: (id: string, active: boolean) => void }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2">
      <input
        type="checkbox"
        checked={active}
        onChange={(e) => onToggle?.(id, e.target.checked)}
        className="h-4 w-4 rounded border-line accent-primary"
      />
      <span className="text-sm text-fg-muted">{active ? "Active" : "Inactive"}</span>
    </label>
  );
}

function RecipientRow({ recipient, onToggle, onDelete }: { recipient: Recipient; onToggle?: (id: string, active: boolean) => void; onDelete?: (id: string) => void }) {
  return (
    <TableRow data-recipient-id={recipient.id}>
      <TableCell className="font-medium text-fg">{recipient.name}</TableCell>
      <TableCell className="text-fg-muted">{recipient.email}</TableCell>
      <TableCell>
        <ChannelBadges channels={recipient.channels} />
      </TableCell>
      <TableCell>
        <ActiveToggle id={recipient.id} active={recipient.active} onToggle={onToggle} />
      </TableCell>
      <TableCell>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => onDelete?.(recipient.id)}>Delete</Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

/**
 * The notification recipients settings page: the settings header, a button to add a recipient, and
 * a table of each recipient with their name, email, channels as badges, an active toggle and
 * actions, alphabetically by name.
 */
export function RecipientsView({ title, view, crumbs, tabs, onAdd, onToggle, onDelete }: RecipientsViewProps) {
  return (
    <div data-slot="settings-recipients" className="flex flex-col gap-6">
      <SettingsHeader title={title} crumbs={crumbs} tabs={tabs} />
      {view.recipients.length === 0 ? (
        <EmptyState
          title="No notification recipients"
          body="There are no notification recipients configured yet."
          action={<Button onClick={onAdd}>Add recipient</Button>}
        />
      ) : (
        <>
          <div className="flex justify-end">
            <Button onClick={onAdd}>Add recipient</Button>
          </div>
          <Table>
            <TableCaption className="text-left text-sm text-fg-muted">
              {view.totalCount} {view.totalCount === 1 ? "recipient" : "recipients"}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Channels</TableHead>
                <TableHead>Active</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.recipients.map((recipient) => (
                <RecipientRow
                  key={recipient.id}
                  recipient={recipient}
                  onToggle={onToggle}
                  onDelete={onDelete}
                />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
