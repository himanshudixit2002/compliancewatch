"use client";

import { useState } from "react";
import {
  Button,
  ReasonDialog,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  VisuallyHidden,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import {
  REASON_MIN_LENGTH,
  REQUEUE_FIELDS,
  isResendable,
  type EventRow,
  type WriteResult,
} from "./pipeline-shared";

export interface OutboxTableProps {
  rows: readonly EventRow[];
  /** The requeue, for an admin; null when the session may only read. */
  action: WriteAction<WriteResult> | null;
}

/**
 * The outbox rows the relay gave up on after its eight sends failed (their message is also on
 * the topic's .dlq), the newest dead first: the topic and key, the attempts and last error, when
 * each went dead, and what the event is about (never its body). An admin requeues one once its
 * cause is fixed: a dialog asks why, the row goes back to pending, and the relay sends it on its
 * next pass. The answer stays above the table while the list renders again without the row.
 */
export function OutboxTable({ rows, action }: OutboxTableProps) {
  const [chosen, setChosen] = useState<EventRow | null>(null);
  const noop: WriteAction<WriteResult> = async (state) => state;
  const { attempt, send, pending, outcomeRef } = useWriteAction(action ?? noop);
  return (
    <div className="flex flex-col gap-3" data-slot="outbox">
      {action === null ? null : (
        <WriteOutcome
          attempt={attempt}
          pending={pending}
          onResend={send}
          outcomeRef={outcomeRef}
          slot="requeue-outcome"
          resendable={isResendable}
        />
      )}
      <Table scrollLabel={t("adminPipeline.outbox.region")}>
        <TableCaption className="text-left text-sm text-fg-muted">
          {t("adminPipeline.outbox.caption", { count: rows.length })}
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>{t("adminPipeline.outbox.column.event")}</TableHead>
            <TableHead>{t("adminPipeline.outbox.column.dead")}</TableHead>
            <TableHead>{t("adminPipeline.outbox.column.error")}</TableHead>
            <TableHead>{t("adminPipeline.outbox.column.about")}</TableHead>
            {action === null ? null : (
              <TableHead>{t("adminPipeline.outbox.column.requeue")}</TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.eventId} data-event={row.eventId} data-topic={row.topic}>
              <TableCell className="align-top">
                <code className="block font-mono text-xs font-medium">{row.topic}</code>
                <span className="block text-xs text-fg-muted">
                  {t("adminPipeline.outbox.key")} <code className="font-mono">{row.key}</code>
                </span>
                <span className="block text-xs text-fg-muted">
                  {t("adminPipeline.outbox.version", {
                    version: row.schemaVersion,
                    bytes: row.payloadBytes,
                  })}
                </span>
                <code className="block font-mono text-xs break-all text-fg-muted">
                  {row.eventId}
                </code>
              </TableCell>
              <TableCell className="align-top text-sm">
                {row.deadAt === null || row.deadAtIso === null ? (
                  t("common.unknown")
                ) : (
                  <time dateTime={row.deadAtIso}>{row.deadAt}</time>
                )}
                <span className="block text-xs text-fg-muted">
                  {t("adminPipeline.outbox.attempts", { count: row.attempts })}
                </span>
                <span className="block text-xs text-fg-muted">
                  {t("adminPipeline.outbox.occurred")}{" "}
                  <time dateTime={row.occurredIso}>{row.occurred}</time>
                </span>
              </TableCell>
              <TableCell className="max-w-md align-top text-sm whitespace-normal text-danger">
                {row.lastError === "" ? (
                  <span className="text-fg-muted">{t("common.none")}</span>
                ) : (
                  row.lastError
                )}
              </TableCell>
              <TableCell className="align-top text-xs">
                {row.summary.length === 0 ? (
                  <span className="text-fg-muted">{t("common.none")}</span>
                ) : (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
                    {row.summary.map(([name, value]) => (
                      <div key={name} className="contents">
                        <dt className="text-fg-muted">{name}</dt>
                        <dd className="font-mono break-all">{value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </TableCell>
              {action === null ? null : (
                <TableCell className="align-top">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={pending}
                    aria-busy={pending || undefined}
                    onClick={() => setChosen(row)}
                  >
                    {t("adminPipeline.outbox.requeue")}
                    <VisuallyHidden>{` ${row.topic} ${row.eventId}`}</VisuallyHidden>
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {chosen === null || action === null ? null : (
        <ReasonDialog
          open
          onOpenChange={(next) => {
            if (!next) setChosen(null);
          }}
          title={t("adminPipeline.outbox.dialogTitle", { topic: chosen.topic })}
          description={t("adminPipeline.outbox.dialogBody")}
          label={t("adminPipeline.reason")}
          hint={t("adminPipeline.reasonHelp", { min: REASON_MIN_LENGTH })}
          confirmLabel={t("adminPipeline.outbox.requeue")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={(reason) => {
            const formData = new FormData();
            formData.set(REQUEUE_FIELDS.eventId, chosen.eventId);
            formData.set(REQUEUE_FIELDS.reason, reason);
            setChosen(null);
            send(formData);
          }}
        />
      )}
    </div>
  );
}
