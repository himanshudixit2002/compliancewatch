"use client";

import { useState } from "react";
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
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { t } from "@/shared/i18n";
import type { ApiKey } from "../model/settings";
import { apiKeyStatusLabel, apiKeyStatusTone } from "../model/settings";

export interface ApiKeysViewProps {
  title: string;
  keys: readonly ApiKey[];
  onCreateKey?: (name: string) => void | Promise<void>;
  onRevokeKey?: (id: string) => void | Promise<void>;
}

interface NewKeyFormProps {
  onSubmit: (name: string) => void | Promise<void>;
  onCancel: () => void;
}

function NewKeyForm({ onSubmit, onCancel }: NewKeyFormProps) {
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) return;
    setPending(true);
    try {
      await onSubmit(name.trim());
      setName("");
    } finally {
      setPending(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      data-slot="new-api-key"
      className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4 sm:flex-row sm:items-end"
      aria-label={t("caSettings.apiKey.createLabel")}
    >
      <div className="flex flex-1 flex-col gap-1">
        <label htmlFor="new-api-key-name" className="text-sm font-medium text-fg">
          {t("caSettings.apiKey.name")}
        </label>
        <Input
          id="new-api-key-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={t("caSettings.apiKey.namePlaceholder")}
          maxLength={120}
          required
          autoComplete="off"
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={pending || !name.trim()}>
          {pending ? t("caSettings.apiKey.creating") : t("caSettings.apiKey.create")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>
          {t("caSettings.cancel")}
        </Button>
      </div>
    </form>
  );
}

export function ApiKeysView({ title, keys, onCreateKey, onRevokeKey }: ApiKeysViewProps) {
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const handleCreate = async (name: string) => {
    if (!onCreateKey) return;
    await onCreateKey(name);
    setCreating(false);
  };

  const handleRevoke = async (id: string) => {
    if (!onRevokeKey) return;
    setRevokingId(id);
    try {
      await onRevokeKey(id);
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <div data-slot="ca-api-keys" className="flex max-w-3xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("caSettings.apiKey.intro")}
        actions={
          onCreateKey && !creating ? (
            <Button onClick={() => setCreating(true)}>{t("caSettings.apiKey.create")}</Button>
          ) : null
        }
      />

      {creating && onCreateKey ? (
        <NewKeyForm onSubmit={handleCreate} onCancel={() => setCreating(false)} />
      ) : null}

      {keys.length === 0 ? (
        <Card>
          <EmptyState
            title={t("caSettings.apiKey.emptyTitle")}
            description={t("caSettings.apiKey.emptyDescription")}
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("caSettings.apiKey.name")}</TableHead>
                <TableHead>{t("caSettings.apiKey.prefix")}</TableHead>
                <TableHead>{t("caSettings.apiKey.created")}</TableHead>
                <TableHead>{t("caSettings.apiKey.lastUsed")}</TableHead>
                <TableHead>{t("caSettings.apiKey.status")}</TableHead>
                <TableHead aria-label={t("caSettings.actions")} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((key) => (
                <TableRow key={key.id}>
                  <TableCell>
                    <div className="flex flex-col gap-1">
                      <span className="font-medium text-fg">{key.name}</span>
                      <code className="text-xs text-fg-muted">{key.id}</code>
                    </div>
                  </TableCell>
                  <TableCell>
                    <code className="text-sm text-fg">{key.keyPrefix}</code>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm text-fg">{formatDate(key.createdAt)}</span>
                  </TableCell>
                  <TableCell>
                    {key.lastUsed ? (
                      <span className="text-sm text-fg">{formatDateTime(key.lastUsed)}</span>
                    ) : (
                      <span className="text-sm text-fg-muted">{t("caSettings.never")}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge tone={apiKeyStatusTone(key.active)}>
                      {apiKeyStatusLabel(key.active)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {key.active && onRevokeKey ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRevoke(key.id)}
                        disabled={revokingId === key.id}
                        aria-busy={revokingId === key.id || undefined}
                      >
                        {revokingId === key.id
                          ? t("caSettings.apiKey.revoking")
                          : t("caSettings.apiKey.revoke")}
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
